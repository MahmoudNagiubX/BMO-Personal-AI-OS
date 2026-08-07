"""Canonical Phase 5A active-model registry and deterministic routing."""

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

ACTIVE_MODELS = (QWEN_4B, BGE_M3)


def route_model(
    capability: Capability | str,
    modalities: frozenset[Modality],
    *,
    requested_model: str | None = None,
) -> ModelIdentity:
    """Resolve only exact Phase 5A capability/modality combinations."""

    if not isinstance(capability, Capability):
        raise ModelGatewayError(
            GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
            "unknown_capability",
            "the requested capability is not supported",
        )

    if capability is Capability.EMBEDDINGS and modalities == frozenset({Modality.TEXT}):
        selected = BGE_M3
    elif (
        capability is Capability.VISION and modalities == frozenset({Modality.TEXT, Modality.IMAGE})
    ) or (
        capability
        in {
            Capability.GENERATION,
            Capability.CHAT,
            Capability.STRUCTURED_OUTPUT,
            Capability.TOOL_CALL_PROPOSAL,
            Capability.MULTILINGUAL,
        }
        and modalities == frozenset({Modality.TEXT})
    ):
        selected = QWEN_4B
    else:
        raise ModelGatewayError(
            GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
            "unsupported_capability_modality",
            "the requested capability and modality combination is not supported",
        )

    if requested_model is not None and requested_model != selected.model_id:
        raise ModelGatewayError(
            GatewayErrorCategory.UNSUPPORTED_CAPABILITY,
            "model_not_routable",
            "the requested model is not routable in Phase 5A",
        )
    return selected


__all__ = ["ACTIVE_MODELS", "BGE_M3", "QWEN_4B", "route_model"]
