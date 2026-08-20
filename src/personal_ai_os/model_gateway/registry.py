"""Canonical model identities and deterministic provider routing."""

from __future__ import annotations

from personal_ai_os.model_gateway.contracts import (
    Capability,
    Modality,
    ModelIdentity,
    ModelRole,
    OutputType,
    Provider,
)
from personal_ai_os.model_gateway.errors import GatewayErrorCategory, ModelGatewayError

QWEN_4B = ModelIdentity(
    provider=Provider.OLLAMA,
    model_id="qwen3.5:4b",
    role=ModelRole.PRIMARY,
    digest="sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd",
    capabilities=frozenset(
        {
            Capability.GENERATION,
            Capability.CHAT,
            Capability.STRUCTURED_OUTPUT,
            Capability.TOOL_CALL_PROPOSAL,
            Capability.VISION,
            Capability.MULTILINGUAL,
        }
    ),
    input_modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
    output_types=frozenset(
        {OutputType.TEXT, OutputType.STRUCTURED_DATA, OutputType.TOOL_CALL_PROPOSAL}
    ),
    context_budgets=(4096, 8192, 16384),
    max_output_tokens=256,
    embedding_dimension=None,
    local_only=True,
)

BGE_M3 = ModelIdentity(
    provider=Provider.OLLAMA,
    model_id="bge-m3:567m",
    role=ModelRole.EMBEDDINGS,
    digest="sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab",
    capabilities=frozenset({Capability.EMBEDDINGS}),
    input_modalities=frozenset({Modality.TEXT}),
    output_types=frozenset({OutputType.EMBEDDING_VECTOR}),
    context_budgets=(),
    max_output_tokens=0,
    embedding_dimension=1024,
    local_only=True,
)

QWEN_9B_HERETIC = ModelIdentity(
    provider=Provider.LLAMA_CPP,
    model_id="qwen3.5-heretic:9b-q4km",
    role=ModelRole.ADVANCED,
    digest="sha256:8d463c63e2c8759ad263cba59f1fa7a0be9a7cacb59b0fd0a787b7daa31597ad",
    capabilities=frozenset({Capability.GENERATION, Capability.CHAT}),
    input_modalities=frozenset({Modality.TEXT}),
    output_types=frozenset({OutputType.TEXT}),
    context_budgets=(4096,),
    max_output_tokens=256,
    embedding_dimension=None,
    local_only=True,
)

# Required Phase 5A/Phase 4 models remain the core health contract.
ACTIVE_MODELS = (QWEN_4B, BGE_M3)
OPTIONAL_MODELS = (QWEN_9B_HERETIC,)
ALL_MODELS = ACTIVE_MODELS + OPTIONAL_MODELS


def route_model(
    capability: Capability | str,
    modalities: frozenset[Modality],
    *,
    requested_model: str | None = None,
) -> ModelIdentity:
    """Resolve a capability/profile pair without fallback or model guessing."""

    if not isinstance(capability, Capability):
        raise ModelGatewayError(
            GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
            "unknown_capability",
            "the requested capability is not supported",
        )

    profile = requested_model
    if profile == "fast":
        profile = QWEN_4B.model_id
    elif profile == "advanced":
        profile = QWEN_9B_HERETIC.model_id

    if capability is Capability.EMBEDDINGS and modalities == frozenset({Modality.TEXT}):
        selected = BGE_M3
    elif capability is Capability.VISION and modalities == frozenset(
        {Modality.TEXT, Modality.IMAGE}
    ):
        selected = QWEN_4B
    elif capability in {
        Capability.GENERATION,
        Capability.CHAT,
        Capability.STRUCTURED_OUTPUT,
        Capability.TOOL_CALL_PROPOSAL,
        Capability.MULTILINGUAL,
    } and modalities == frozenset({Modality.TEXT}):
        selected = QWEN_9B_HERETIC if profile == QWEN_9B_HERETIC.model_id else QWEN_4B
        if selected is QWEN_9B_HERETIC and capability not in {
            Capability.GENERATION,
            Capability.CHAT,
        }:
            raise ModelGatewayError(
                GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
                "advanced_capability_not_supported",
                "the advanced local model is text generation and chat only",
            )
    else:
        raise ModelGatewayError(
            GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
            "unsupported_capability_modality",
            "the requested capability and modality combination is not supported",
        )

    if profile is not None and profile != selected.model_id:
        raise ModelGatewayError(
            GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
            "model_not_routable",
            "the requested model is not routable for this capability",
        )
    return selected


__all__ = [
    "ACTIVE_MODELS",
    "ALL_MODELS",
    "BGE_M3",
    "OPTIONAL_MODELS",
    "QWEN_4B",
    "QWEN_9B_HERETIC",
    "route_model",
]
