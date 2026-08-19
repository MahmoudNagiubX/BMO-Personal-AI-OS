"""SQLAlchemy rows that make Phase 8 decisions and executions durable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_ai_os.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ToolCall(Base):
    """One immutable request identity with state transitions guarded by row locks."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'validated', 'denied', 'awaiting_approval', 'approved', "
            "'executing', 'succeeded', 'failed', 'rejected', 'expired', 'cancelled')",
            name="ck_tool_calls_status",
        ),
        CheckConstraint(
            "risk_level IN ('read', 'reversible', 'consequential', 'critical', "
            "'forbidden_autonomous')",
            name="ck_tool_calls_risk",
        ),
        Index("ix_tool_calls_owner_created", "owner_id", "created_at"),
        Index("ix_tool_calls_run_status", "run_id", "status"),
        UniqueConstraint(
            "owner_id",
            "device_id",
            "tool_name",
            "idempotency_key",
            name="uq_tool_calls_idempotency",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    credential_id: Mapped[UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="SET NULL")
    )
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    argument_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="phase8-v1")
    decision: Mapped[str | None] = mapped_column(String(24))
    reason_code: Mapped[str | None] = mapped_column(String(96))
    approval_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(96))


class PermissionDecision(Base):
    """Append-oriented deterministic policy decision fact."""

    __tablename__ = "permission_decisions"
    __table_args__ = (Index("ix_permission_decisions_tool_call", "tool_call_id", "decided_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tool_call_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tool_calls.id", ondelete="CASCADE")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    argument_digest: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Approval(Base):
    """Owner approval bound to one tool call and one canonical argument digest."""

    __tablename__ = "tool_approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled', 'consumed')",
            name="ck_tool_approvals_status",
        ),
        Index("ix_tool_approvals_owner_status", "owner_id", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tool_call_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    requesting_device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    decision_device_id: Mapped[UUID | None] = mapped_column(Uuid)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    argument_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolObservationRow(Base):
    """Typed execution result and verification fact."""

    __tablename__ = "tool_observations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tool_call_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    verification_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AuditEvent(Base):
    """Redacted append-only audit event; raw credentials and raw model output are excluded."""

    __tablename__ = "tool_audit_events"
    __table_args__ = (
        Index("ix_tool_audit_events_owner_time", "owner_id", "occurred_at"),
        Index("ix_tool_audit_events_tool_call_time", "tool_call_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="SET NULL")
    )
    device_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tool_calls.id", ondelete="SET NULL")
    )
    approval_id: Mapped[UUID | None] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128))
    tool_version: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[str | None] = mapped_column(String(32))
    reason_code: Mapped[str | None] = mapped_column(String(96))
    argument_digest: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    immutable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class ToolRateBucket(Base):
    """Database-backed fixed-window rate counter."""

    __tablename__ = "tool_rate_buckets"
    __table_args__ = (Index("ix_tool_rate_buckets_device_tool", "device_id", "tool_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = [
    "Approval",
    "AuditEvent",
    "PermissionDecision",
    "ToolCall",
    "ToolObservationRow",
    "ToolRateBucket",
]
