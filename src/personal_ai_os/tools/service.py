"""Transactional Phase 8 permission, approval, execution, and audit service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from personal_ai_os.conversations.models import AgentRun
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.identity.models import Device, DeviceCapability
from personal_ai_os.tools.contracts import (
    ApprovalResponse,
    ApprovalStatus,
    AuditResponse,
    AvailabilityState,
    PermissionDecisionKind,
    RiskLevel,
    ToolCallRequest,
    ToolCallResponse,
    ToolCallStatus,
    ToolCatalogItem,
    ToolExecutionRequest,
    ToolObservation,
    ToolObservationStatus,
)
from personal_ai_os.tools.errors import (
    ApprovalError,
    ToolBudgetError,
    ToolConflictError,
    ToolDeniedError,
    ToolNotFoundError,
    ToolSchemaError,
)
from personal_ai_os.tools.executor import SyntheticToolExecutor
from personal_ai_os.tools.models import (
    Approval,
    AuditEvent,
    PermissionDecision,
    ToolCall,
    ToolObservationRow,
)
from personal_ai_os.tools.registry import (
    ToolDescriptor,
    ToolRegistry,
    argument_digest,
    deterministic_preview,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PermissionResult:
    decision: PermissionDecisionKind
    reason_code: str


class ToolPlatformService:
    """The only authority permitted to transition a validated tool call to execution."""

    MAX_PROPOSALS_PER_RUN = 4
    MAX_EXECUTIONS_PER_RUN = 3
    MAX_APPROVALS_PER_RUN = 2

    def __init__(
        self,
        session: Session,
        *,
        registry: ToolRegistry | None = None,
        clock: Clock = _utc_now,
        executor: SyntheticToolExecutor | None = None,
        availability: Callable[[ToolDescriptor], AvailabilityState] | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or ToolRegistry(())
        if registry is None:
            from personal_ai_os.tools.registry import default_registry

            self.registry = default_registry()
        self.clock = clock
        self.executor = executor or SyntheticToolExecutor()
        self.availability = availability or self._default_availability

    @staticmethod
    def _default_availability(descriptor: ToolDescriptor) -> AvailabilityState:
        if descriptor.availability_policy == "offline":
            return AvailabilityState.OFFLINE
        return AvailabilityState.AVAILABLE

    def catalog(self, *, include_disabled: bool = False) -> list[ToolCatalogItem]:
        return [
            self._catalog_item(item)
            for item in self.registry.catalog()
            if include_disabled or item.enabled
        ]

    def request_tool(
        self, principal: DevicePrincipal, request: ToolCallRequest
    ) -> ToolCallResponse:
        """Validate, authorize, and durably stage one request; never accepts policy from caller."""

        try:
            descriptor = self.registry.resolve(request.name, request.version)
        except ToolNotFoundError:
            self._unbound_audit(
                principal,
                request.name,
                request.version,
                "tool.denied",
                "unknown_tool_version",
            )
            raise
        try:
            arguments = self.registry.validate_arguments(descriptor, request.arguments)
            digest = argument_digest(arguments)
        except ToolSchemaError:
            self._unbound_audit(
                principal, request.name, request.version, "tool.denied", "input_schema_invalid"
            )
            raise
        now = self.clock()
        try:
            with self.session.begin():
                existing = self.session.scalar(
                    select(ToolCall)
                    .where(
                        ToolCall.owner_id == principal.owner_id,
                        ToolCall.device_id == principal.device_id,
                        ToolCall.tool_name == request.name,
                        ToolCall.idempotency_key == request.idempotency_key,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    if (
                        existing.argument_digest != digest
                        or existing.tool_version != request.version
                    ):
                        raise ToolConflictError("idempotency_argument_mismatch")
                    return self._response(existing, replayed=True)

                self._require_scope(principal, "tool.request")
                self._enforce_proposal_budget(request.run_id, principal)
                self._enforce_rate_limit(descriptor, principal, now)
                call = ToolCall(
                    owner_id=principal.owner_id,
                    device_id=principal.device_id,
                    credential_id=principal.credential_id,
                    conversation_id=request.conversation_id,
                    run_id=request.run_id,
                    tool_name=descriptor.name,
                    tool_version=descriptor.version,
                    risk_level=descriptor.risk_level.value,
                    status=ToolCallStatus.PROPOSED.value,
                    arguments_json=arguments,
                    argument_digest=digest,
                    idempotency_key=request.idempotency_key,
                    policy_version="phase8-v1",
                    created_at=now,
                )
                self.session.add(call)
                self.session.flush()
                call.status = ToolCallStatus.VALIDATED.value
                call.validated_at = now
                self._audit(call, "tool.proposed", reason_code="validated", occurred_at=now)
                result = self._permission(descriptor, principal, call, now)
                call.decision = result.decision.value
                call.reason_code = result.reason_code
                self.session.add(
                    PermissionDecision(
                        tool_call_id=call.id,
                        owner_id=principal.owner_id,
                        device_id=principal.device_id,
                        tool_name=descriptor.name,
                        tool_version=descriptor.version,
                        risk_level=descriptor.risk_level.value,
                        decision=result.decision.value,
                        reason_code=result.reason_code,
                        argument_digest=digest,
                        policy_version="phase8-v1",
                        decided_at=now,
                    )
                )
                if result.decision is PermissionDecisionKind.DENY:
                    call.status = ToolCallStatus.DENIED.value
                    self._audit(
                        call, "tool.denied", reason_code=result.reason_code, occurred_at=now
                    )
                elif result.decision is PermissionDecisionKind.REQUIRE_APPROVAL:
                    self._enforce_approval_budget(request.run_id, principal)
                    approval = Approval(
                        tool_call_id=call.id,
                        owner_id=principal.owner_id,
                        requesting_device_id=principal.device_id,
                        tool_name=descriptor.name,
                        tool_version=descriptor.version,
                        risk_level=descriptor.risk_level.value,
                        argument_digest=digest,
                        preview_json=deterministic_preview(descriptor, arguments),
                        policy_version="phase8-v1",
                        status=ApprovalStatus.PENDING.value,
                        created_at=now,
                        expires_at=now
                        + timedelta(
                            minutes=3 if descriptor.risk_level is RiskLevel.CRITICAL else 10
                        ),
                    )
                    self.session.add(approval)
                    self.session.flush()
                    call.approval_id = approval.id
                    call.status = ToolCallStatus.AWAITING_APPROVAL.value
                    self._audit(
                        call,
                        "tool.awaiting_approval",
                        reason_code="owner_approval_required",
                        occurred_at=now,
                        approval_id=approval.id,
                    )
                    self._audit(
                        call,
                        "approval.required",
                        reason_code="owner_approval_required",
                        occurred_at=now,
                        approval_id=approval.id,
                    )
                else:
                    call.status = ToolCallStatus.APPROVED.value
                    self._audit(call, "tool.approved", reason_code="policy_allow", occurred_at=now)
                self.session.flush()
                return self._response(call, replayed=False)
        except IntegrityError as error:
            self.session.rollback()
            replay = self._find_idempotent(principal, request.name, request.idempotency_key)
            if replay is not None and replay.argument_digest == digest:
                return self._response(replay, replayed=True)
            raise ToolConflictError("idempotency_race_conflict") from error

    def decide_approval(
        self, principal: DevicePrincipal, approval_id: UUID, *, approve: bool
    ) -> ApprovalResponse:
        self._require_scope(principal, "approval.decide")
        now = self.clock()
        with self.session.begin():
            approval = self.session.scalar(
                select(Approval).where(Approval.id == approval_id).with_for_update()
            )
            if approval is None or approval.owner_id != principal.owner_id:
                raise ApprovalError("approval_not_available")
            call = self.session.scalar(
                select(ToolCall).where(ToolCall.id == approval.tool_call_id).with_for_update()
            )
            if call is None or call.owner_id != principal.owner_id:
                raise ApprovalError("approval_binding_invalid")
            if approval.status != ApprovalStatus.PENDING.value:
                raise ApprovalError("approval_not_pending")
            if _aware(approval.expires_at) <= _aware(now):
                approval.status = ApprovalStatus.EXPIRED.value
                call.status = ToolCallStatus.EXPIRED.value
                call.reason_code = "approval_expired"
                self._audit(
                    call,
                    "approval.expired",
                    reason_code="approval_expired",
                    occurred_at=now,
                    approval_id=approval.id,
                )
                raise ApprovalError("approval_expired")
            approval.decision_device_id = principal.device_id
            approval.decided_at = now
            if approve:
                approval.status = ApprovalStatus.APPROVED.value
                call.status = ToolCallStatus.APPROVED.value
                call.reason_code = "owner_approved"
                self._audit(
                    call,
                    "approval.approved",
                    reason_code="owner_approved",
                    occurred_at=now,
                    approval_id=approval.id,
                )
            else:
                approval.status = ApprovalStatus.REJECTED.value
                call.status = ToolCallStatus.REJECTED.value
                call.reason_code = "owner_rejected"
                self._audit(
                    call,
                    "approval.rejected",
                    reason_code="owner_rejected",
                    occurred_at=now,
                    approval_id=approval.id,
                )
            self.session.flush()
            return self._approval_response(approval)

    def execute_tool_call(
        self,
        principal: DevicePrincipal,
        tool_call_id: UUID,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> ToolObservation:
        """Atomically consume authority, then execute only the typed bound request."""

        now = self.clock()
        with self.session.begin():
            call = self.session.scalar(
                select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
            )
            if (
                call is None
                or call.owner_id != principal.owner_id
                or call.device_id != principal.device_id
            ):
                raise ToolDeniedError("tool_call_not_available")
            descriptor = self.registry.resolve(call.tool_name, call.tool_version)
            if arguments is not None:
                validated = self.registry.validate_arguments(descriptor, arguments)
                if argument_digest(validated) != call.argument_digest:
                    raise ToolConflictError("argument_binding_mismatch")
            if call.status in {
                ToolCallStatus.SUCCEEDED.value,
                ToolCallStatus.FAILED.value,
                ToolCallStatus.CANCELLED.value,
                ToolCallStatus.REJECTED.value,
                ToolCallStatus.DENIED.value,
                ToolCallStatus.EXPIRED.value,
            }:
                existing = self.session.scalar(
                    select(ToolObservationRow).where(ToolObservationRow.tool_call_id == call.id)
                )
                if existing is not None:
                    return self._observation(existing)
                raise ToolConflictError("tool_call_terminal")
            if call.status != ToolCallStatus.APPROVED.value:
                raise ApprovalError("execution_not_approved")
            if call.approval_id is not None:
                approval = self.session.scalar(
                    select(Approval).where(Approval.id == call.approval_id).with_for_update()
                )
                if approval is None or approval.status != ApprovalStatus.APPROVED.value:
                    raise ApprovalError("approval_not_consumable")
                if _aware(approval.expires_at) <= _aware(now):
                    approval.status = ApprovalStatus.EXPIRED.value
                    call.status = ToolCallStatus.EXPIRED.value
                    call.reason_code = "approval_expired"
                    self._audit(
                        call,
                        "approval.expired",
                        reason_code="approval_expired",
                        occurred_at=now,
                        approval_id=approval.id,
                    )
                    raise ApprovalError("approval_expired")
                approval.status = ApprovalStatus.CONSUMED.value
                approval.consumed_at = now
            self._enforce_execution_budget(call.run_id, principal)
            call.status = ToolCallStatus.EXECUTING.value
            call.started_at = now
            self._audit(call, "tool.started", reason_code="authority_consumed", occurred_at=now)
            request = ToolExecutionRequest(
                tool_call_id=call.id,
                name=call.tool_name,
                version=call.tool_version,
                owner_id=call.owner_id,
                device_id=call.device_id,
                arguments=dict(call.arguments_json),
                argument_digest=call.argument_digest,
                sandbox_policy=descriptor.sandbox_policy,
                timeout_seconds=descriptor.timeout_seconds,
            )
        raw = self.executor.execute(request)
        try:
            output = self.registry.validate_output(descriptor, raw.output)
        except ToolSchemaError:
            observation = ToolObservation(
                status=ToolObservationStatus.FAILED,
                output={},
                verification={"verified": False},
                failure_code="output_schema_invalid",
            )
        else:
            if (
                raw.status is not ToolObservationStatus.SUCCEEDED
                or raw.verification.get("verified") is not True
            ):
                observation = ToolObservation(
                    status=ToolObservationStatus.FAILED,
                    output=output,
                    verification=raw.verification,
                    failure_code=raw.failure_code or "verification_failed",
                )
            else:
                observation = ToolObservation(
                    status=ToolObservationStatus.SUCCEEDED,
                    output=output,
                    verification=raw.verification,
                )
        with self.session.begin():
            call = self.session.scalar(
                select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
            )
            if call is None:
                raise ToolConflictError("tool_call_disappeared")
            call.status = observation.status.value
            call.completed_at = self.clock()
            call.failure_code = observation.failure_code
            self.session.add(
                ToolObservationRow(
                    tool_call_id=call.id,
                    status=observation.status.value,
                    output_json=observation.output,
                    verification_json=observation.verification,
                    failure_code=observation.failure_code,
                    observed_at=observation.observed_at,
                )
            )
            self._audit(
                call,
                "tool.succeeded"
                if observation.status is ToolObservationStatus.SUCCEEDED
                else "tool.failed",
                reason_code=observation.failure_code or "verified",
                occurred_at=self.clock(),
            )
        return observation

    def cancel_tool_call(self, principal: DevicePrincipal, tool_call_id: UUID) -> ToolCallResponse:
        self._require_scope(principal, "tool.request")
        now = self.clock()
        with self.session.begin():
            call = self.session.scalar(
                select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
            )
            if (
                call is None
                or call.owner_id != principal.owner_id
                or call.device_id != principal.device_id
            ):
                raise ToolDeniedError("tool_call_not_available")
            if call.status == ToolCallStatus.EXECUTING.value:
                raise ToolConflictError("execution_not_cancellable")
            if call.status in {
                ToolCallStatus.SUCCEEDED.value,
                ToolCallStatus.FAILED.value,
                ToolCallStatus.CANCELLED.value,
            }:
                return self._response(call, replayed=True)
            call.status = ToolCallStatus.CANCELLED.value
            call.reason_code = "caller_cancelled"
            if call.approval_id is not None:
                approval = self.session.scalar(
                    select(Approval).where(Approval.id == call.approval_id).with_for_update()
                )
                if approval is not None and approval.status == ApprovalStatus.PENDING.value:
                    approval.status = ApprovalStatus.CANCELLED.value
            self._audit(call, "tool.cancelled", reason_code="caller_cancelled", occurred_at=now)
            return self._response(call, replayed=False)

    def expire_pending(self) -> int:
        now = self.clock()
        count = 0
        with self.session.begin():
            approvals = list(
                self.session.scalars(
                    select(Approval)
                    .where(
                        Approval.status == ApprovalStatus.PENDING.value,
                        Approval.expires_at <= now,
                    )
                    .with_for_update()
                )
            )
            for approval in approvals:
                approval.status = ApprovalStatus.EXPIRED.value
                call = self.session.scalar(
                    select(ToolCall).where(ToolCall.id == approval.tool_call_id).with_for_update()
                )
                if call is not None and call.status == ToolCallStatus.AWAITING_APPROVAL.value:
                    call.status = ToolCallStatus.EXPIRED.value
                    call.reason_code = "approval_expired"
                    self._audit(
                        call,
                        "approval.expired",
                        reason_code="approval_expired",
                        occurred_at=now,
                        approval_id=approval.id,
                    )
                count += 1
        return count

    def approvals(self, principal: DevicePrincipal, *, limit: int = 50) -> list[ApprovalResponse]:
        self._require_scope(principal, "approval.read")
        with self.session.begin():
            rows = list(
                self.session.scalars(
                    select(Approval)
                    .where(Approval.owner_id == principal.owner_id)
                    .order_by(Approval.created_at.desc())
                    .limit(limit)
                )
            )
            return [self._approval_response(row) for row in rows]

    def approval(self, principal: DevicePrincipal, approval_id: UUID) -> ApprovalResponse:
        self._require_scope(principal, "approval.read")
        with self.session.begin():
            row = self.session.scalar(
                select(Approval).where(
                    Approval.id == approval_id,
                    Approval.owner_id == principal.owner_id,
                )
            )
            if row is None:
                raise ApprovalError("approval_not_available")
            return self._approval_response(row)

    def audit(self, principal: DevicePrincipal, *, limit: int = 100) -> list[AuditResponse]:
        self._require_scope(principal, "audit.read")
        with self.session.begin():
            rows = list(
                self.session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.owner_id == principal.owner_id)
                    .order_by(AuditEvent.occurred_at.desc())
                    .limit(limit)
                )
            )
            return [
                AuditResponse(
                    id=row.id,
                    event_type=row.event_type,
                    tool_name=row.tool_name,
                    tool_version=row.tool_version,
                    risk_level=RiskLevel(row.risk_level) if row.risk_level else None,
                    result=row.result,
                    reason_code=row.reason_code,
                    argument_digest=row.argument_digest,
                    metadata=dict(row.metadata_json),
                    occurred_at=row.occurred_at,
                )
                for row in rows
            ]

    def _permission(
        self, descriptor: ToolDescriptor, principal: DevicePrincipal, call: ToolCall, now: datetime
    ) -> PermissionResult:
        if not descriptor.enabled:
            return PermissionResult(PermissionDecisionKind.DENY, "tool_disabled")
        if descriptor.required_request_scopes - principal.scopes:
            return PermissionResult(PermissionDecisionKind.DENY, "scope_missing")
        if descriptor.required_device_capabilities:
            capabilities = set(
                self.session.scalars(
                    select(DeviceCapability.capability).where(
                        DeviceCapability.device_id == principal.device_id
                    )
                )
            )
            if not descriptor.required_device_capabilities.issubset(capabilities):
                return PermissionResult(PermissionDecisionKind.DENY, "capability_missing")
        state = self.availability(descriptor)
        if state is not AvailabilityState.AVAILABLE:
            return PermissionResult(PermissionDecisionKind.DENY, f"availability_{state.value}")
        if descriptor.risk_level is RiskLevel.FORBIDDEN_AUTONOMOUS:
            return PermissionResult(PermissionDecisionKind.DENY, "forbidden_autonomous")
        if descriptor.approval_policy.value == "exact_owner":
            return PermissionResult(
                PermissionDecisionKind.REQUIRE_APPROVAL, "owner_approval_required"
            )
        return PermissionResult(PermissionDecisionKind.ALLOW, "policy_allow")

    def _enforce_proposal_budget(self, run_id: UUID | None, principal: DevicePrincipal) -> None:
        self._lock_budget_anchor(run_id, principal)
        query = (
            select(func.count())
            .select_from(ToolCall)
            .where(ToolCall.owner_id == principal.owner_id)
        )
        if run_id is None:
            query = query.where(
                ToolCall.device_id == principal.device_id, ToolCall.run_id.is_(None)
            )
        else:
            query = query.where(ToolCall.run_id == run_id)
        if (self.session.scalar(query) or 0) >= self.MAX_PROPOSALS_PER_RUN:
            raise ToolBudgetError("proposal_budget_exhausted")

    def _enforce_approval_budget(self, run_id: UUID | None, principal: DevicePrincipal) -> None:
        self._lock_budget_anchor(run_id, principal)
        query = (
            select(func.count())
            .select_from(ToolCall)
            .where(
                ToolCall.owner_id == principal.owner_id,
                ToolCall.decision == PermissionDecisionKind.REQUIRE_APPROVAL.value,
            )
        )
        query = (
            query.where(ToolCall.run_id == run_id)
            if run_id is not None
            else query.where(ToolCall.device_id == principal.device_id, ToolCall.run_id.is_(None))
        )
        if (self.session.scalar(query) or 0) >= self.MAX_APPROVALS_PER_RUN:
            raise ToolBudgetError("approval_budget_exhausted")

    def _enforce_execution_budget(self, run_id: UUID | None, principal: DevicePrincipal) -> None:
        self._lock_budget_anchor(run_id, principal)
        query = (
            select(func.count())
            .select_from(ToolCall)
            .where(
                ToolCall.owner_id == principal.owner_id,
                ToolCall.status.in_(
                    [ToolCallStatus.EXECUTING.value, ToolCallStatus.SUCCEEDED.value]
                ),
            )
        )
        query = (
            query.where(ToolCall.run_id == run_id)
            if run_id is not None
            else query.where(ToolCall.device_id == principal.device_id, ToolCall.run_id.is_(None))
        )
        if (self.session.scalar(query) or 0) >= self.MAX_EXECUTIONS_PER_RUN:
            raise ToolBudgetError("execution_budget_exhausted")

    def _enforce_rate_limit(
        self, descriptor: ToolDescriptor, principal: DevicePrincipal, now: datetime
    ) -> None:
        self._lock_budget_anchor(None, principal)
        lower = now - timedelta(seconds=descriptor.rate_limit_policy[1])
        count = self.session.scalar(
            select(func.count())
            .select_from(ToolCall)
            .where(
                ToolCall.device_id == principal.device_id,
                ToolCall.tool_name == descriptor.name,
                ToolCall.created_at >= lower,
            )
        )
        if (count or 0) >= descriptor.rate_limit_policy[0]:
            raise ToolBudgetError("rate_limit_exhausted")

    def _lock_budget_anchor(self, run_id: UUID | None, principal: DevicePrincipal) -> None:
        """Serialize counters on a durable PostgreSQL row before counting."""

        if run_id is not None:
            run = self.session.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None:
                raise ToolConflictError("run_binding_invalid")
            return
        device = self.session.scalar(
            select(Device).where(Device.id == principal.device_id).with_for_update()
        )
        if device is None:
            raise ToolDeniedError("device_not_available")

    def _require_scope(self, principal: DevicePrincipal, scope: str) -> None:
        if scope not in principal.scopes:
            raise ToolDeniedError("scope_missing")

    def _find_idempotent(self, principal: DevicePrincipal, name: str, key: str) -> ToolCall | None:
        with self.session.begin():
            return self.session.scalar(
                select(ToolCall).where(
                    ToolCall.owner_id == principal.owner_id,
                    ToolCall.device_id == principal.device_id,
                    ToolCall.tool_name == name,
                    ToolCall.idempotency_key == key,
                )
            )

    def _unbound_audit(
        self, principal: DevicePrincipal, name: str, version: int, event: str, reason: str
    ) -> None:
        with self.session.begin():
            self.session.add(
                AuditEvent(
                    owner_id=principal.owner_id,
                    device_id=principal.device_id,
                    event_type=event,
                    tool_name=name,
                    tool_version=version,
                    reason_code=reason,
                    metadata_json={"bound": False},
                    occurred_at=self.clock(),
                )
            )

    def _audit(
        self,
        call: ToolCall,
        event: str,
        *,
        reason_code: str,
        occurred_at: datetime,
        approval_id: UUID | None = None,
    ) -> None:
        self.session.add(
            AuditEvent(
                owner_id=call.owner_id,
                device_id=call.device_id,
                tool_call_id=call.id,
                approval_id=approval_id,
                event_type=event,
                tool_name=call.tool_name,
                tool_version=call.tool_version,
                risk_level=call.risk_level,
                result=call.status,
                reason_code=reason_code,
                argument_digest=call.argument_digest,
                metadata_json={"redacted": True, "policy_version": call.policy_version},
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def _catalog_item(item: ToolDescriptor) -> ToolCatalogItem:
        return ToolCatalogItem(
            name=item.name,
            version=item.version,
            description=item.description,
            owner_kind=item.owner_kind,
            execution_target=item.execution_target,
            input_schema=item.input_schema(),
            output_schema=item.output_schema(),
            required_request_scopes=sorted(item.required_request_scopes),
            required_device_capabilities=sorted(item.required_device_capabilities),
            risk_level=item.risk_level,
            approval_policy=item.approval_policy,
            availability_policy=item.availability_policy,
            timeout_seconds=item.timeout_seconds,
            idempotency_policy=item.idempotency_policy,
            rate_limit_policy=item.rate_limit,
            budget_cost=item.budget_cost,
            audit_redaction_policy=item.audit_redaction_policy,
            verification_policy=item.verification_policy,
            reversal_policy=item.reversal_policy,
            sandbox_policy=item.sandbox_policy,
            enabled=item.enabled,
        )

    def _response(self, call: ToolCall, *, replayed: bool) -> ToolCallResponse:
        return ToolCallResponse(
            id=call.id,
            name=call.tool_name,
            version=call.tool_version,
            status=ToolCallStatus(call.status),
            decision=PermissionDecisionKind(call.decision) if call.decision else None,
            reason_code=call.reason_code,
            argument_digest=call.argument_digest,
            approval_id=call.approval_id,
            replayed=replayed,
            created_at=call.created_at,
        )

    def _approval_response(self, approval: Approval) -> ApprovalResponse:
        return ApprovalResponse(
            id=approval.id,
            tool_call_id=approval.tool_call_id,
            name=approval.tool_name,
            version=approval.tool_version,
            risk_level=RiskLevel(approval.risk_level),
            status=ApprovalStatus(approval.status),
            preview=dict(approval.preview_json),
            argument_digest=approval.argument_digest,
            created_at=approval.created_at,
            expires_at=approval.expires_at,
            decided_at=approval.decided_at,
        )

    def _observation(self, row: ToolObservationRow) -> ToolObservation:
        return ToolObservation(
            status=ToolObservationStatus(row.status),
            output=dict(row.output_json),
            verification=dict(row.verification_json),
            failure_code=row.failure_code,
            observed_at=row.observed_at,
        )


__all__ = ["ToolPlatformService"]
