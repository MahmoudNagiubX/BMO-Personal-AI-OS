from __future__ import annotations

import logging
import threading

import pytest

from personal_ai_os.model_gateway import (
    QWEN_4B,
    Availability,
    Capability,
    EmbeddingRequest,
    GatewayErrorCategory,
    GatewaySettings,
    GenerationRequest,
    Message,
    MessageRole,
    ModelGateway,
    ModelGatewayError,
)
from personal_ai_os.model_gateway.contracts import HealthReason, ProviderModel
from personal_ai_os.model_gateway.provider import (
    ProviderContractError,
    ProviderOfflineError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from personal_ai_os.model_gateway.resilience import CircuitBreaker, CircuitState
from tests.unit.model_gateway.fakes import FakeClock, FakeProvider


def request(request_id: str = "phase-05a-resilience") -> GenerationRequest:
    return GenerationRequest(
        request_id=request_id,
        capability=Capability.GENERATION,
        messages=(Message(MessageRole.USER, "Synthetic retry prompt"),),
    )


def open_circuit(provider: FakeProvider, clock: FakeClock) -> ModelGateway:
    provider.generation_failures = [
        ProviderTransientError("one"),
        ProviderTransientError("two"),
    ]
    gateway = ModelGateway(
        provider,
        GatewaySettings(max_attempts=1, circuit_failure_threshold=2),
        clock=clock,
        sleeper=lambda _: None,
    )
    for suffix in ("one", "two"):
        with pytest.raises(ModelGatewayError):
            gateway.generate(request(f"phase-05a-open-{suffix}"))
    assert gateway.circuit.state is CircuitState.OPEN
    return gateway


def test_health_available_uses_only_version_and_inventory() -> None:
    provider = FakeProvider()
    health = ModelGateway(provider).health()
    assert health.availability is Availability.AVAILABLE
    assert health.reason is HealthReason.READY
    assert health.provider_version == "0.32.5"
    assert all(item.present and item.identity_matches for item in health.required_models)
    assert provider.version_calls == 1
    assert provider.inventory_calls == 1
    assert provider.generation_calls == 0
    assert provider.embedding_calls == 0


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (ProviderOfflineError("private raw detail"), HealthReason.PROVIDER_UNREACHABLE),
        (ProviderTimeoutError("private raw detail"), HealthReason.PROVIDER_TIMEOUT),
    ],
)
def test_health_offline_is_typed_and_sanitized(failure: Exception, reason: HealthReason) -> None:
    provider = FakeProvider()
    provider.version_failures = [failure]
    health = ModelGateway(provider).health()
    assert health.availability is Availability.OFFLINE
    assert health.reason is reason
    assert "private raw detail" not in repr(health)


def test_unexpected_health_failure_is_sanitized_as_degraded() -> None:
    provider = FakeProvider()
    provider.version_failures = [RuntimeError("raw private provider detail")]
    health = ModelGateway(provider).health()
    assert health.availability is Availability.DEGRADED
    assert health.reason is HealthReason.PROVIDER_CONTRACT_VIOLATION
    assert "raw private" not in repr(health)


def test_online_missing_model_is_degraded_not_offline() -> None:
    provider = FakeProvider()
    provider.models = tuple(
        model for model in provider.models if model.model_id != QWEN_4B.model_id
    )
    health = ModelGateway(provider).health()
    assert health.availability is Availability.DEGRADED
    assert health.reason is HealthReason.MODEL_MISSING
    assert provider.version_calls == 1


def test_online_digest_or_version_mismatch_is_degraded() -> None:
    provider = FakeProvider()
    provider.models = tuple(
        ProviderModel(model.model_id, "sha256:" + "f" * 64)
        if model.model_id == QWEN_4B.model_id
        else model
        for model in provider.models
    )
    health = ModelGateway(provider).health()
    assert health.availability is Availability.DEGRADED
    assert health.reason is HealthReason.MODEL_IDENTITY_MISMATCH

    provider = FakeProvider()
    provider.version_value = "unexpected"
    health = ModelGateway(provider).health()
    assert health.availability is Availability.DEGRADED
    assert health.reason is HealthReason.PROVIDER_VERSION_MISMATCH


def test_disabled_gateway_is_offline_without_transport() -> None:
    provider = FakeProvider()
    gateway = ModelGateway(provider, GatewaySettings(enabled=False))
    assert gateway.health().reason is HealthReason.GATEWAY_DISABLED
    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.generate(request())
    assert exc_info.value.category is GatewayErrorCategory.PROVIDER_UNAVAILABLE
    assert provider.version_calls == provider.inventory_calls == provider.generation_calls == 0


def test_transient_failure_retries_once_then_succeeds() -> None:
    provider = FakeProvider()
    provider.generation_failures = [ProviderTransientError("raw first failure")]
    sleeps: list[float] = []
    gateway = ModelGateway(provider, sleeper=sleeps.append)
    response = gateway.generate(request())
    assert response.text == "synthetic response"
    assert provider.generation_calls == 2
    assert provider.inventory_calls == 2
    assert sleeps == [0.05]
    assert gateway.circuit.state is CircuitState.CLOSED


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (ProviderOfflineError("raw offline"), GatewayErrorCategory.PROVIDER_UNAVAILABLE),
        (ProviderTimeoutError("raw timeout"), GatewayErrorCategory.TIMEOUT),
        (
            ProviderTransientError("raw transient"),
            GatewayErrorCategory.PROVIDER_TRANSIENT_FAILURE,
        ),
    ],
)
def test_transient_classes_stop_at_two_attempts_without_raw_leakage(
    failure: Exception, category: GatewayErrorCategory
) -> None:
    provider = FakeProvider()
    provider.generation_failures = [failure, type(failure)(str(failure))]
    gateway = ModelGateway(provider, sleeper=lambda _: None)
    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.generate(request())
    assert exc_info.value.category is category
    assert exc_info.value.attempts == 2
    assert provider.generation_calls == 2
    assert "raw" not in str(exc_info.value)


def test_circuit_opens_fails_fast_and_successful_half_open_probe_closes() -> None:
    provider = FakeProvider()
    provider.generation_failures = [
        ProviderTransientError("one"),
        ProviderTransientError("two"),
    ]
    clock = FakeClock()
    settings = GatewaySettings(max_attempts=1, circuit_failure_threshold=2)
    gateway = ModelGateway(provider, settings, clock=clock, sleeper=lambda _: None)

    for suffix in ("one", "two"):
        with pytest.raises(ModelGatewayError):
            gateway.generate(request(f"phase-05a-{suffix}"))
    assert gateway.circuit.state is CircuitState.OPEN
    calls_at_open = provider.generation_calls
    with pytest.raises(ModelGatewayError) as open_error:
        gateway.generate(request("phase-05a-open"))
    assert open_error.value.reason_code == "circuit_open"
    assert provider.generation_calls == calls_at_open

    clock.advance(31)
    response = gateway.generate(request("phase-05a-half-open"))
    assert response.text == "synthetic response"
    assert gateway.circuit.state is CircuitState.CLOSED
    assert gateway.circuit.failure_count == 0


def test_failed_half_open_probe_reopens_circuit() -> None:
    provider = FakeProvider()
    provider.generation_failures = [
        ProviderTransientError("one"),
        ProviderTransientError("two"),
        ProviderTransientError("probe"),
    ]
    clock = FakeClock()
    gateway = ModelGateway(
        provider,
        GatewaySettings(max_attempts=1, circuit_failure_threshold=2),
        clock=clock,
        sleeper=lambda _: None,
    )
    for suffix in ("one", "two"):
        with pytest.raises(ModelGatewayError):
            gateway.generate(request(f"phase-05a-fail-{suffix}"))
    clock.advance(31)
    with pytest.raises(ModelGatewayError):
        gateway.generate(request("phase-05a-probe-fail"))
    assert gateway.circuit.state is CircuitState.OPEN


def test_half_open_model_missing_releases_probe_and_later_request_succeeds() -> None:
    provider = FakeProvider()
    original_models = provider.models
    clock = FakeClock()
    gateway = open_circuit(provider, clock)
    provider.models = tuple(
        model for model in provider.models if model.model_id != QWEN_4B.model_id
    )
    clock.advance(31)

    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.generate(request("phase-05a-half-open-missing"))
    assert exc_info.value.reason_code == "model_missing"
    assert gateway.circuit.state is CircuitState.CLOSED
    assert gateway.circuit.failure_count == 0

    provider.models = original_models
    response = gateway.generate(request("phase-05a-after-missing"))
    assert response.text == "synthetic response"
    assert provider.generation_calls == 3


def test_half_open_digest_mismatch_releases_probe_and_later_request_succeeds() -> None:
    provider = FakeProvider()
    original_models = provider.models
    clock = FakeClock()
    gateway = open_circuit(provider, clock)
    provider.models = tuple(
        ProviderModel(model.model_id, "sha256:" + "0" * 64)
        if model.model_id == QWEN_4B.model_id
        else model
        for model in provider.models
    )
    clock.advance(31)

    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.generate(request("phase-05a-half-open-mismatch"))
    assert exc_info.value.category is GatewayErrorCategory.MODEL_IDENTITY_MISMATCH
    assert gateway.circuit.state is CircuitState.CLOSED
    assert gateway.circuit.failure_count == 0

    provider.models = original_models
    response = gateway.generate(request("phase-05a-after-mismatch"))
    assert response.text == "synthetic response"
    assert provider.generation_calls == 3


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (ProviderRequestError("synthetic request failure"), "provider_request_rejected"),
        (ProviderContractError("synthetic contract failure"), "provider_contract_violation"),
    ],
)
def test_half_open_deterministic_provider_failure_releases_probe_without_retry(
    failure: Exception, reason: str
) -> None:
    provider = FakeProvider()
    clock = FakeClock()
    gateway = open_circuit(provider, clock)
    provider.generation_failures = [failure]
    clock.advance(31)

    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.generate(request("phase-05a-half-open-provider"))
    assert exc_info.value.category is GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION
    assert exc_info.value.reason_code == reason
    assert exc_info.value.attempts == 1
    assert gateway.circuit.state is CircuitState.CLOSED
    assert gateway.circuit.failure_count == 0
    assert provider.generation_calls == 3

    response = gateway.generate(request("phase-05a-after-provider"))
    assert response.text == "synthetic response"
    assert provider.generation_calls == 4


def test_direct_half_open_non_transient_completion_closes_and_releases_probe() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30, clock=clock)
    breaker.before_call()
    breaker.record_transient_failure()
    breaker.before_call()
    breaker.record_transient_failure()
    assert breaker.state is CircuitState.OPEN

    clock.advance(31)
    breaker.before_call()
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.record_non_transient_result()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.failure_count == 0
    breaker.before_call()


def test_invalid_requests_do_not_change_circuit_or_call_transport() -> None:
    provider = FakeProvider()
    gateway = ModelGateway(provider)
    with pytest.raises(ModelGatewayError):
        gateway.generate(
            GenerationRequest(
                request_id="phase-05a-invalid",
                capability=Capability.GENERATION,
                messages=(),
            )
        )
    assert gateway.circuit.state is CircuitState.CLOSED
    assert gateway.circuit.failure_count == 0
    assert provider.inventory_calls == provider.generation_calls == 0


def test_unsupported_deferred_model_does_not_count_or_retry() -> None:
    provider = FakeProvider()
    gateway = ModelGateway(provider)
    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.generate(
            GenerationRequest(
                request_id="phase-05a-no-nine-b",
                capability=Capability.GENERATION,
                messages=(Message(MessageRole.USER, "Synthetic"),),
                requested_model="qwen3.5:9b",
            )
        )
    assert exc_info.value.category is GatewayErrorCategory.UNSUPPORTED_CAPABILITY
    assert gateway.circuit.failure_count == 0
    assert provider.inventory_calls == provider.generation_calls == 0


def test_one_request_at_a_time_returns_typed_busy_for_second_request() -> None:
    provider = FakeProvider()
    provider.entered = threading.Event()
    provider.release = threading.Event()
    gateway = ModelGateway(provider, GatewaySettings(concurrency_wait_seconds=0.01))
    first_errors: list[BaseException] = []

    def run_first() -> None:
        try:
            gateway.generate(request("phase-05a-first"))
        except BaseException as exc:  # pragma: no cover - assertion captures unexpected failure
            first_errors.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    assert provider.entered.wait(timeout=1)
    with pytest.raises(ModelGatewayError) as exc_info:
        gateway.embed(EmbeddingRequest(request_id="phase-05a-second", texts=("synthetic",)))
    assert exc_info.value.category is GatewayErrorCategory.BUSY
    provider.release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert first_errors == []
    assert provider.max_active_calls == 1
    assert provider.embedding_calls == 0


def test_sensitive_request_content_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    provider = FakeProvider()
    secret_marker = "synthetic-private-prompt-marker"
    with caplog.at_level(logging.DEBUG):
        ModelGateway(provider).generate(
            GenerationRequest(
                request_id="phase-05a-log",
                capability=Capability.GENERATION,
                messages=(Message(MessageRole.USER, secret_marker),),
            )
        )
    assert secret_marker not in caplog.text


def test_offline_generation_and_embedding_have_no_cloud_fallback_or_retry_storm() -> None:
    generation_provider = FakeProvider()
    generation_provider.inventory_failures = [
        ProviderOfflineError("offline"),
        ProviderOfflineError("offline"),
    ]
    with pytest.raises(ModelGatewayError) as generation_error:
        ModelGateway(generation_provider, sleeper=lambda _: None).generate(request())
    assert generation_error.value.category is GatewayErrorCategory.PROVIDER_UNAVAILABLE
    assert generation_provider.inventory_calls == 2
    assert generation_provider.generation_calls == 0

    embedding_provider = FakeProvider()
    embedding_provider.inventory_failures = [
        ProviderOfflineError("offline"),
        ProviderOfflineError("offline"),
    ]
    with pytest.raises(ModelGatewayError) as embedding_error:
        ModelGateway(embedding_provider, sleeper=lambda _: None).embed(
            EmbeddingRequest(request_id="phase-05a-offline-embed", texts=("synthetic",))
        )
    assert embedding_error.value.category is GatewayErrorCategory.PROVIDER_UNAVAILABLE
    assert embedding_provider.inventory_calls == 2
    assert embedding_provider.embedding_calls == 0
