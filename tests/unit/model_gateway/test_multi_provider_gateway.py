from __future__ import annotations

import pytest

from personal_ai_os.model_gateway import (
    QWEN_9B_HERETIC,
    Capability,
    EmbeddingRequest,
    GatewayErrorCategory,
    GatewaySettings,
    GenerationRequest,
    Message,
    MessageRole,
    ModelGateway,
    ModelGatewayError,
    Provider,
)
from personal_ai_os.model_gateway.contracts import ProviderModel
from personal_ai_os.model_gateway.provider import ProviderOfflineError, ProviderTransientError
from tests.unit.model_gateway.fakes import FakeProvider


def request(request_id: str, *, model: str | None = None) -> GenerationRequest:
    return GenerationRequest(
        request_id=request_id,
        capability=Capability.CHAT,
        messages=(Message(MessageRole.USER, "Synthetic gateway request"),),
        requested_model=model,
    )


def advanced_provider() -> FakeProvider:
    provider = FakeProvider()
    provider.version_value = "b10502-0adcc3bb5"
    provider.models = (ProviderModel(QWEN_9B_HERETIC.model_id, QWEN_9B_HERETIC.digest),)
    return provider


class OfflineAdvancedProvider(FakeProvider):
    """Optional provider whose process is unavailable for isolation proofs."""

    def inventory(self, *, timeout_seconds: float):
        del timeout_seconds
        raise ProviderOfflineError("synthetic llama.cpp process is down")

    def ensure_sleeping(self, *, timeout_seconds: float) -> bool:
        del timeout_seconds
        raise ProviderOfflineError("synthetic llama.cpp process is down")


def test_optional_advanced_failure_does_not_degrade_required_core() -> None:
    fast = FakeProvider()
    advanced = advanced_provider()
    advanced.version_failures = [ProviderOfflineError("synthetic advanced outage")]
    gateway = ModelGateway({Provider.OLLAMA: fast, Provider.LLAMA_CPP: advanced}, GatewaySettings())

    health = gateway.health()

    assert health.availability.value == "available"
    assert health.advanced_availability.value == "offline"
    assert health.advanced_models[0].model_id == QWEN_9B_HERETIC.model_id


def test_advanced_circuit_isolated_from_fast_circuit() -> None:
    fast = FakeProvider()
    advanced = advanced_provider()
    advanced.generation_failures = [ProviderTransientError("one")]
    gateway = ModelGateway(
        {
            Provider.OLLAMA: fast,
            Provider.LLAMA_CPP: advanced,
        },
        GatewaySettings(max_attempts=1, circuit_failure_threshold=1),
        sleeper=lambda _: None,
    )

    with pytest.raises(ModelGatewayError):
        gateway.generate(request("advanced-failure", model="advanced"))
    response = gateway.generate(request("fast-success"))

    assert response.model.provider is Provider.OLLAMA
    assert gateway.circuit.state.value == "closed"
    assert gateway.circuit_for(QWEN_9B_HERETIC).state.value == "open"


def test_advanced_unavailable_fails_without_fast_fallback() -> None:
    fast = FakeProvider()
    gateway = ModelGateway(fast)

    with pytest.raises(ModelGatewayError) as error:
        gateway.generate(request("advanced-unavailable", model="advanced"))

    assert error.value.category is GatewayErrorCategory.PROVIDER_UNAVAILABLE
    assert fast.generation_calls == 0


def test_optional_provider_down_does_not_block_fast_or_bge_and_keeps_circuits_isolated() -> None:
    fast = FakeProvider()
    advanced = OfflineAdvancedProvider()
    gateway = ModelGateway(
        {Provider.OLLAMA: fast, Provider.LLAMA_CPP: advanced},
        GatewaySettings(max_attempts=1),
    )

    fast_response = gateway.generate(request("fast-while-advanced-down"))
    embedding_response = gateway.embed(
        EmbeddingRequest(request_id="bge-while-advanced-down", texts=("synthetic",))
    )

    assert fast_response.model.provider is Provider.OLLAMA
    assert embedding_response.dimension == 1024
    assert fast.generation_calls == 1
    assert fast.embedding_calls == 1
    assert gateway.circuit.state.value == "closed"

    with pytest.raises(ModelGatewayError) as error:
        gateway.generate(request("advanced-while-down", model="advanced"))

    assert error.value.category is GatewayErrorCategory.PROVIDER_UNAVAILABLE
    assert error.value.reason_code == "provider_offline"
    assert gateway.circuit.state.value == "closed"
    assert gateway.circuit_for(QWEN_9B_HERETIC).state.value == "closed"


def test_generation_timeout_is_selected_after_provider_model_routing() -> None:
    fast = FakeProvider()
    advanced = advanced_provider()
    gateway = ModelGateway({Provider.OLLAMA: fast, Provider.LLAMA_CPP: advanced}, GatewaySettings())

    gateway.generate(request("fast-timeout"))
    gateway.generate(request("advanced-timeout", model="advanced"))

    assert fast.generation_timeouts == [60.0]
    assert advanced.generation_timeouts == [180.0]
