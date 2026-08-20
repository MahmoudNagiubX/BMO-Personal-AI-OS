from __future__ import annotations

import json
from ipaddress import ip_address
from pathlib import Path

import pytest
from pydantic import ValidationError

from personal_ai_os.model_gateway import (
    ACTIVE_MODELS,
    ALL_MODELS,
    BGE_M3,
    QWEN_4B,
    QWEN_9B_HERETIC,
    Capability,
    GatewayErrorCategory,
    GatewaySettings,
    Modality,
    ModelGatewayError,
    OllamaProvider,
    route_model,
)
from personal_ai_os.model_gateway.contracts import ModelRole, OutputType

ROOT = Path(__file__).resolve().parents[3]


def test_registry_contains_only_exact_phase_four_active_models() -> None:
    assert [model.role for model in ACTIVE_MODELS] == [
        ModelRole.PRIMARY,
        ModelRole.EMBEDDINGS,
    ]
    assert QWEN_4B.model_id == "qwen3.5:4b"
    assert QWEN_4B.digest == (
        "sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
    )
    assert QWEN_4B.context_budgets == (4096, 8192, 16384)
    assert QWEN_4B.max_output_tokens == 256
    assert QWEN_4B.local_only is True
    assert BGE_M3.model_id == "bge-m3:567m"
    assert BGE_M3.digest == (
        "sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
    )
    assert BGE_M3.embedding_dimension == 1024
    assert BGE_M3.output_types == frozenset({OutputType.EMBEDDING_VECTOR})
    assert all("9b" not in model.model_id.casefold() for model in ACTIVE_MODELS)


def test_registry_matches_phase_four_manifest_without_using_evidence() -> None:
    manifest = json.loads(
        (ROOT / "infrastructure/tuf/model_manifest.json").read_text(encoding="utf-8")
    )
    expected = {(model.role.value, model.model_id, model.digest) for model in ACTIVE_MODELS}
    actual = {(model["role"], model["tag"], model["digest"]) for model in manifest["models"]}
    assert actual == expected


def test_optional_advanced_registry_is_exact_and_text_only() -> None:
    assert QWEN_9B_HERETIC.provider.value == "llama_cpp"
    assert QWEN_9B_HERETIC.role is ModelRole.ADVANCED
    assert QWEN_9B_HERETIC.context_budgets == (4096,)
    assert QWEN_9B_HERETIC.capabilities == frozenset({Capability.GENERATION, Capability.CHAT})
    assert QWEN_9B_HERETIC.input_modalities == frozenset({Modality.TEXT})
    assert QWEN_9B_HERETIC.output_types == frozenset({OutputType.TEXT})
    assert QWEN_9B_HERETIC in ALL_MODELS


def test_advanced_provider_activation_has_a_deterministic_deployment_path() -> None:
    settings = GatewaySettings()

    assert settings.llama_cpp_enabled is True
    assert settings.llama_cpp_model_path
    assert settings.llama_cpp_model_path.casefold().endswith(
        "qwen3.5-9b-ultra-uncensored-heretic-v2-q4_k_m.gguf"
    )
    with pytest.raises(ValidationError):
        GatewaySettings(llama_cpp_model_path=" ")


@pytest.mark.parametrize("requested_model", ["advanced", QWEN_9B_HERETIC.model_id])
def test_advanced_generation_route_is_explicit(requested_model: str) -> None:
    assert (
        route_model(
            Capability.CHAT,
            frozenset({Modality.TEXT}),
            requested_model=requested_model,
        )
        is QWEN_9B_HERETIC
    )


def test_advanced_route_rejects_vision_tools_and_embedding() -> None:
    for capability, modalities in (
        (Capability.VISION, frozenset({Modality.TEXT, Modality.IMAGE})),
        (Capability.TOOL_CALL_PROPOSAL, frozenset({Modality.TEXT})),
        (Capability.EMBEDDINGS, frozenset({Modality.TEXT})),
    ):
        with pytest.raises(ModelGatewayError):
            route_model(capability, modalities, requested_model="advanced")


@pytest.mark.parametrize(
    ("capability", "modalities", "expected"),
    [
        (Capability.GENERATION, frozenset({Modality.TEXT}), QWEN_4B),
        (Capability.CHAT, frozenset({Modality.TEXT}), QWEN_4B),
        (Capability.STRUCTURED_OUTPUT, frozenset({Modality.TEXT}), QWEN_4B),
        (Capability.TOOL_CALL_PROPOSAL, frozenset({Modality.TEXT}), QWEN_4B),
        (Capability.VISION, frozenset({Modality.TEXT, Modality.IMAGE}), QWEN_4B),
        (Capability.EMBEDDINGS, frozenset({Modality.TEXT}), BGE_M3),
    ],
)
def test_routing_is_exact_and_deterministic(
    capability: Capability, modalities: frozenset[Modality], expected: object
) -> None:
    assert route_model(capability, modalities) is expected


@pytest.mark.parametrize(
    ("capability", "modalities", "requested_model"),
    [
        (Capability.GENERATION, frozenset({Modality.IMAGE}), None),
        (Capability.EMBEDDINGS, frozenset({Modality.IMAGE}), None),
        (Capability.EMBEDDINGS, frozenset({Modality.TEXT, Modality.IMAGE}), None),
        (Capability.GENERATION, frozenset({Modality.TEXT}), BGE_M3.model_id),
        (Capability.EMBEDDINGS, frozenset({Modality.TEXT}), QWEN_4B.model_id),
        (Capability.GENERATION, frozenset({Modality.TEXT}), "qwen3.5:9b"),
        ("audio", frozenset({Modality.TEXT}), None),
    ],
)
def test_invalid_or_deferred_routes_fail_closed(
    capability: Capability | str,
    modalities: frozenset[Modality],
    requested_model: str | None,
) -> None:
    with pytest.raises(ModelGatewayError) as exc_info:
        route_model(capability, modalities, requested_model=requested_model)
    assert exc_info.value.category is GatewayErrorCategory.UNSUPPORTED_CAPABILITY


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://0.0.0.0:11434",
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://8.8.8.8:11434",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434/api/chat",
        "https://api.openai.com:443",
    ],
)
def test_unsafe_provider_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        GatewaySettings(ollama_endpoint=endpoint)
    with pytest.raises(ValueError):
        OllamaProvider(endpoint)


def test_loopback_is_allowed_and_private_ip_requires_explicit_future_flag() -> None:
    settings = GatewaySettings(ollama_endpoint="http://127.0.0.1:11434")
    assert settings.ollama_endpoint == "http://127.0.0.1:11434"
    private_endpoint = f"http://{ip_address(0x0A000005)}:11434"
    with pytest.raises(ValidationError):
        GatewaySettings(ollama_endpoint=private_endpoint)
    explicit = GatewaySettings(
        ollama_endpoint=private_endpoint,
        allow_private_network_endpoint=True,
    )
    assert explicit.ollama_endpoint == private_endpoint


def test_gateway_configuration_has_no_cloud_or_api_key_fields() -> None:
    field_names = set(GatewaySettings.model_fields)
    assert not any("api_key" in name or "cloud" in name for name in field_names)
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").casefold()
    gateway_source = "\n".join(
        path.read_text(encoding="utf-8").casefold()
        for path in (ROOT / "src/personal_ai_os/model_gateway").glob("*.py")
    )
    for cloud_provider in ("api.openai.com", "anthropic", "gemini", "groq", "openrouter"):
        assert cloud_provider not in project
        assert cloud_provider not in gateway_source


def test_ollama_adapter_exposes_no_lifecycle_or_arbitrary_endpoint_methods() -> None:
    provider = OllamaProvider("http://127.0.0.1:11434")
    for forbidden in ("pull", "delete", "install", "update", "start", "stop", "request"):
        assert not hasattr(provider, forbidden)
