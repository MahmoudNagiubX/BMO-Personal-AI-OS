"""Typed provider-neutral model gateway contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Provider(StrEnum):
    OLLAMA = "ollama"


class ModelRole(StrEnum):
    PRIMARY = "primary"
    EMBEDDINGS = "embeddings"


class Capability(StrEnum):
    GENERATION = "generation"
    CHAT = "chat"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALL_PROPOSAL = "tool_call_proposal"
    VISION = "vision"
    MULTILINGUAL = "multilingual"
    EMBEDDINGS = "embeddings"


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    EMBEDDING_VECTOR = "embedding_vector"


class OutputType(StrEnum):
    TEXT = "text"
    STRUCTURED_DATA = "structured_data"
    TOOL_CALL_PROPOSAL = "tool_call_proposal"
    EMBEDDING_VECTOR = "embedding_vector"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Availability(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class HealthReason(StrEnum):
    READY = "ready"
    GATEWAY_DISABLED = "gateway_disabled"
    PROVIDER_UNREACHABLE = "provider_unreachable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_VERSION_MISMATCH = "provider_version_mismatch"
    MODEL_MISSING = "model_missing"
    MODEL_IDENTITY_MISMATCH = "model_identity_mismatch"
    PROVIDER_CONTRACT_VIOLATION = "provider_contract_violation"


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider: Provider
    model_id: str
    role: ModelRole
    digest: str
    capabilities: frozenset[Capability]
    input_modalities: frozenset[Modality]
    output_types: frozenset[OutputType]
    context_budgets: tuple[int, ...]
    max_output_tokens: int
    embedding_dimension: int | None
    local_only: bool


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    text: str


@dataclass(frozen=True, slots=True)
class ImageInput:
    media_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolProposal:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    request_id: str
    capability: Capability
    messages: tuple[Message, ...]
    context_tokens: int = 4096
    max_output_tokens: int = 128
    timeout_seconds: float | None = None
    images: tuple[ImageInput, ...] = ()
    structured_schema: Mapping[str, Any] | None = None
    tools: tuple[ToolDefinition, ...] = ()
    requested_model: str | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    request_id: str
    model: ModelIdentity
    text: str
    structured_value: Any | None
    tool_proposals: tuple[ToolProposal, ...]
    usage: Usage
    finish_reason: str
    latency_seconds: float


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    request_id: str
    texts: tuple[str, ...]
    timeout_seconds: float | None = None
    requested_model: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    request_id: str
    model: ModelIdentity
    vectors: tuple[tuple[float, ...], ...]
    dimension: int
    count: int
    latency_seconds: float


@dataclass(frozen=True, slots=True)
class ModelPresence:
    model_id: str
    present: bool
    identity_matches: bool


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    provider: Provider
    availability: Availability
    observed_at: datetime
    latency_seconds: float
    required_models: tuple[ModelPresence, ...]
    reason: HealthReason
    provider_version: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderModel:
    model_id: str
    digest: str


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderGenerationResult:
    text: str
    finish_reason: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    tool_calls: tuple[ProviderToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderGenerationRequest:
    model_id: str
    messages: tuple[Message, ...]
    images: tuple[ImageInput, ...]
    context_tokens: int
    max_output_tokens: int
    structured_schema: Mapping[str, Any] | None
    tools: tuple[ToolDefinition, ...]


@dataclass(frozen=True, slots=True)
class ProviderEmbeddingResult:
    vectors: tuple[tuple[float, ...], ...] = field(default_factory=tuple)


__all__ = [
    "Availability",
    "Capability",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "GenerationRequest",
    "GenerationResponse",
    "HealthReason",
    "HealthSnapshot",
    "ImageInput",
    "Message",
    "MessageRole",
    "Modality",
    "ModelIdentity",
    "ModelPresence",
    "ModelRole",
    "OutputType",
    "Provider",
    "ProviderEmbeddingResult",
    "ProviderGenerationRequest",
    "ProviderGenerationResult",
    "ProviderModel",
    "ProviderToolCall",
    "ToolDefinition",
    "ToolProposal",
    "Usage",
]
