"""Strict HTTP and event contracts for text conversations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from personal_ai_os.identity.contracts import StrictContract

ConversationStatus = Literal["active", "archived"]
SessionStatus = Literal["active", "closed"]
MessageRole = Literal["user", "assistant"]
RunStatus = Literal["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"]


class ConversationCreateRequest(StrictContract):
    """Bounded optional title for a new durable conversation."""

    title: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ConversationResponse(StrictContract):
    """Sanitized conversation metadata."""

    id: UUID
    owner_id: UUID
    created_by_device_id: UUID
    title: str | None
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class ConversationSessionCreateRequest(StrictContract):
    """Empty request kept explicit for a stable API boundary."""


class ConversationSessionResponse(StrictContract):
    """Sanitized device-attributed session metadata."""

    id: UUID
    conversation_id: UUID
    owner_id: UUID
    device_id: UUID
    status: SessionStatus
    created_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None


class MessageSubmitRequest(StrictContract):
    """One bounded user message with a durable idempotency key."""

    client_message_id: UUID = Field(strict=False)
    content: str = Field(min_length=1, max_length=4000)
    model: Literal["fast", "advanced"] = "fast"

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class MessageResponse(StrictContract):
    """Canonical conversation message; content is intentionally owner-scoped."""

    id: UUID
    conversation_id: UUID
    session_id: UUID | None
    run_id: UUID | None
    author_device_id: UUID | None
    role: MessageRole
    content: str
    ordinal: int
    created_at: datetime


class RunResponse(StrictContract):
    """Factual, sanitized run history and lifecycle state."""

    id: UUID
    conversation_id: UUID
    session_id: UUID
    request_device_id: UUID
    trigger_message_id: UUID
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    cancel_requested_at: datetime | None
    completed_at: datetime | None
    model_request_id: str | None
    requested_model: str | None
    executed_provider: str | None
    model_id: str | None
    model_digest: str | None
    finish_reason: str | None
    prompt_usage: int | None
    output_usage: int | None
    latency_ms: float | None
    failure_category: str | None
    failure_code: str | None
    correlation_id: str | None
    context_truncated: bool
    event_sequence_start: int | None
    event_sequence_end: int | None


class SubmitMessageResponse(StrictContract):
    """Accepted or idempotently replayed submission identifiers."""

    message: MessageResponse
    run: RunResponse
    replayed: bool


class EventEnvelope(StrictContract):
    """Versioned outbound lifecycle event envelope."""

    schema_version: Literal["phase-07-event/v1"] = "phase-07-event/v1"
    sequence: int
    event_type: str
    conversation_id: UUID
    session_id: UUID
    run_id: UUID | None
    occurred_at: datetime
    data: dict[str, Any]


class CancelResponse(StrictContract):
    """Current truthful state after a cancellation request."""

    run: RunResponse


__all__ = [
    "CancelResponse",
    "ConversationCreateRequest",
    "ConversationResponse",
    "ConversationSessionCreateRequest",
    "ConversationSessionResponse",
    "EventEnvelope",
    "MessageResponse",
    "MessageSubmitRequest",
    "RunResponse",
    "SubmitMessageResponse",
]
