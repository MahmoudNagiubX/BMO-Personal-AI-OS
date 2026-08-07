"""BMO-owned software-only model gateway."""

from personal_ai_os.model_gateway.config import GatewaySettings
from personal_ai_os.model_gateway.contracts import (
    Availability,
    Capability,
    EmbeddingRequest,
    EmbeddingResponse,
    GenerationRequest,
    GenerationResponse,
    HealthSnapshot,
    ImageInput,
    Message,
    MessageRole,
    Modality,
    ModelIdentity,
    ToolDefinition,
    ToolProposal,
)
from personal_ai_os.model_gateway.errors import GatewayErrorCategory, ModelGatewayError
from personal_ai_os.model_gateway.gateway import ModelGateway
from personal_ai_os.model_gateway.ollama import OllamaProvider
from personal_ai_os.model_gateway.registry import ACTIVE_MODELS, BGE_M3, QWEN_4B, route_model

__all__ = [
    "ACTIVE_MODELS",
    "BGE_M3",
    "QWEN_4B",
    "Availability",
    "Capability",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "GatewayErrorCategory",
    "GatewaySettings",
    "GenerationRequest",
    "GenerationResponse",
    "HealthSnapshot",
    "ImageInput",
    "Message",
    "MessageRole",
    "Modality",
    "ModelGateway",
    "ModelGatewayError",
    "ModelIdentity",
    "OllamaProvider",
    "ToolDefinition",
    "ToolProposal",
    "route_model",
]
