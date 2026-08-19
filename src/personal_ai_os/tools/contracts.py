"""Strict, provider-neutral Phase 8 tool platform contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictContract(BaseModel):
    """Reject extra fields and coercion at every tool boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class RiskLevel(StrEnum):
    READ = "read"
    REVERSIBLE = "reversible"
    CONSEQUENTIAL = "consequential"
    CRITICAL = "critical"
    FORBIDDEN_AUTONOMOUS = "forbidden_autonomous"


class ApprovalPolicy(StrEnum):
    NONE = "none"
    EXACT_OWNER = "exact_owner"


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class PermissionDecisionKind(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ToolCallStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    DENIED = "denied"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"


class ToolObservationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SandboxPolicy(StrEnum):
    CORE_READONLY = "core_readonly"
    SATELLITE_TYPED = "satellite_typed"
    BROWSER_ISOLATED = "browser_isolated"
    HOME_ASSISTANT_SELECTED = "home_assistant_selected"
    FORBIDDEN = "forbidden"


class ToolCallRequest(StrictContract):
    """Only caller-controlled fields accepted by the tool request API."""

    name: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1, le=99)
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=16, max_length=128)
    conversation_id: UUID | None = None
    run_id: UUID | None = None


class ToolCallResponse(StrictContract):
    id: UUID
    name: str
    version: int
    status: ToolCallStatus
    decision: PermissionDecisionKind | None
    reason_code: str | None
    argument_digest: str
    approval_id: UUID | None
    replayed: bool
    created_at: datetime


class ApprovalResponse(StrictContract):
    id: UUID
    tool_call_id: UUID
    name: str
    version: int
    risk_level: RiskLevel
    status: ApprovalStatus
    preview: dict[str, Any]
    argument_digest: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None


class ApprovalDecisionRequest(StrictContract):
    approve: bool


class ToolCatalogItem(StrictContract):
    name: str
    version: int
    description: str
    owner_kind: str
    execution_target: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_request_scopes: list[str]
    required_device_capabilities: list[str]
    risk_level: RiskLevel
    approval_policy: ApprovalPolicy
    availability_policy: str
    timeout_seconds: float
    idempotency_policy: str
    rate_limit_policy: dict[str, int]
    budget_cost: int
    audit_redaction_policy: str
    verification_policy: str
    reversal_policy: str
    sandbox_policy: SandboxPolicy
    enabled: bool


class AuditResponse(StrictContract):
    id: UUID
    event_type: str
    tool_name: str | None
    tool_version: int | None
    risk_level: RiskLevel | None
    result: str | None
    reason_code: str | None
    argument_digest: str | None
    metadata: dict[str, Any]
    occurred_at: datetime


class ToolObservation(StrictContract):
    status: ToolObservationStatus
    output: dict[str, Any]
    verification: dict[str, Any]
    failure_code: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolExecutionRequest(StrictContract):
    """Executor input; it contains validated arguments and binding facts only."""

    tool_call_id: UUID
    name: str
    version: int
    owner_id: UUID
    device_id: UUID
    arguments: dict[str, Any]
    argument_digest: str
    sandbox_policy: SandboxPolicy
    timeout_seconds: float


__all__ = [
    "ApprovalDecisionRequest",
    "ApprovalPolicy",
    "ApprovalResponse",
    "ApprovalStatus",
    "AuditResponse",
    "AvailabilityState",
    "PermissionDecisionKind",
    "RiskLevel",
    "SandboxPolicy",
    "ToolCallRequest",
    "ToolCallResponse",
    "ToolCallStatus",
    "ToolCatalogItem",
    "ToolExecutionRequest",
    "ToolObservation",
    "ToolObservationStatus",
]
