"""SQLAlchemy persistence models for Phase 7 conversations and runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_ai_os.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-created rows."""

    return datetime.now(UTC)


class Conversation(Base):
    """Durable owner-scoped conversation thread."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_conversations_status"),
        CheckConstraint(
            "title IS NULL OR length(title) BETWEEN 1 AND 200",
            name="ck_conversations_title",
        ),
        Index("ix_conversations_owner_updated", "owner_id", "updated_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationSession(Base):
    """Bounded live interaction window tied to one owner device."""

    __tablename__ = "conversation_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="ck_conversation_sessions_status"),
        Index("ix_conversation_sessions_owner_device", "owner_id", "device_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMessage(Base):
    """Canonical user or verified assistant content."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role"),
        CheckConstraint(
            "length(content) BETWEEN 1 AND 4000", name="ck_conversation_messages_content"
        ),
        UniqueConstraint("conversation_id", "ordinal", name="uq_conversation_message_ordinal"),
        Index("ix_conversation_messages_conversation_created", "conversation_id", "ordinal"),
        Index(
            "uq_conversation_message_client_id",
            "conversation_id",
            "author_device_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
            sqlite_where=text("client_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_sessions.id", ondelete="SET NULL")
    )
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    author_device_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    client_message_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class AgentRun(Base):
    """One bounded attempt to produce one verified assistant message."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'succeeded', 'failed', "
            "'cancelled')",
            name="ck_agent_runs_status",
        ),
        Index("ix_agent_runs_conversation_created", "conversation_id", "created_at"),
        Index(
            "uq_agent_runs_one_active_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'cancel_requested')"),
            sqlite_where=text("status IN ('queued', 'running', 'cancel_requested')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    request_device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    trigger_message_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_messages.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_request_id: Mapped[str | None] = mapped_column(String(128))
    model_id: Mapped[str | None] = mapped_column(String(64))
    model_digest: Mapped[str | None] = mapped_column(String(80))
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    prompt_usage: Mapped[int | None] = mapped_column(Integer)
    output_usage: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column()
    failure_category: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    context_truncated: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    event_sequence_start: Mapped[int | None] = mapped_column(Integer)
    event_sequence_end: Mapped[int | None] = mapped_column(Integer)


class RunEvent(Base):
    """Sanitized lifecycle fact persisted for WebSocket replay."""

    __tablename__ = "run_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_run_events_sequence"),
        CheckConstraint("length(event_type) BETWEEN 1 AND 64", name="ck_run_events_type"),
        UniqueConstraint("session_id", "sequence", name="uq_run_events_session_sequence"),
        Index("ix_run_events_session_sequence", "session_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
