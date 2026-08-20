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
    Provider,
    ToolDefinition,
    ToolProposal,
)
from personal_ai_os.model_gateway.errors import GatewayErrorCategory, ModelGatewayError
from personal_ai_os.model_gateway.gateway import ModelGateway
from personal_ai_os.model_gateway.llama_cpp import LlamaCppProvider
from personal_ai_os.model_gateway.ollama import OllamaProvider
from personal_ai_os.model_gateway.registry import (
    ACTIVE_MODELS,
    ALL_MODELS,
    BGE_M3,
    OPTIONAL_MODELS,
    QWEN_4B,
    QWEN_9B_HERETIC,
    route_model,
)

__all__ = [
    "ACTIVE_MODELS",
    "ALL_MODELS",
    "BGE_M3",
    "OPTIONAL_MODELS",
    "QWEN_4B",
    "QWEN_9B_HERETIC",
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
    "LlamaCppProvider",
    "Message",
    "MessageRole",
    "Modality",
    "ModelGateway",
    "ModelGatewayError",
    "ModelIdentity",
    "OllamaProvider",
    "Provider",
    "ToolDefinition",
    "ToolProposal",
    "route_model",
]
