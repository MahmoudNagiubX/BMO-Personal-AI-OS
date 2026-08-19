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

from personal_ai_os.conversations.models import (
    AgentRun,
    Conversation,
    ConversationSession,
    RunEvent,
)
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.identity.models import Device, DeviceCapability, Owner
from personal_ai_os.tools.contracts import (
    ApprovalPolicy,
    ApprovalResponse,
    ApprovalStatus,
    AuditResponse,
    AvailabilityState,
    PermissionDecisionKind,
    RiskLevel,
    SandboxPolicy,
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
    ToolPlatformError,
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

    def _tx(self) -> Any:
        if self.session.in_transaction():
            return self.session.begin_nested()
        return self.session.begin()

    def catalog(self, *, include_disabled: bool = False) -> list[ToolCatalogItem]:
        return [
            self._catalog_item(item)
            for item in self.registry.catalog()
            if include_disabled or item.enabled
        ]

    def _validate_context_binding(
        self,
        principal: DevicePrincipal,
        conversation_id: UUID | None,
        run_id: UUID | None,
    ) -> tuple[Conversation | None, AgentRun | None]:
        """Validate ownership, device attribution, and compatibility of run/conversation."""

        if run_id is not None:
            run = self.session.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None:
                raise ToolConflictError("run_binding_invalid")
            conversation = self.session.scalar(
                select(Conversation).where(Conversation.id == run.conversation_id)
            )
            if conversation is None or conversation.owner_id != principal.owner_id:
                raise ToolDeniedError("tool_call_not_available")
            session = self.session.scalar(
                select(ConversationSession).where(ConversationSession.id == run.session_id)
            )
            if session is None or session.owner_id != principal.owner_id:
                raise ToolDeniedError("tool_call_not_available")
            if (
                session.device_id != principal.device_id
                and run.request_device_id != principal.device_id
            ):
                raise ToolDeniedError("device_session_mismatch")
            if session.status != "active":
                raise ToolConflictError("session_closed")
            if conversation.status != "active":
                raise ToolConflictError("conversation_inactive")
            if conversation_id is not None and conversation_id != run.conversation_id:
                raise ToolConflictError("conversation_run_mismatch")
            if run.status in {"succeeded", "failed", "cancelled"}:
                raise ToolConflictError("run_terminal")
            return conversation, run

        if conversation_id is not None:
            conversation = self.session.scalar(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            if conversation is None or conversation.owner_id != principal.owner_id:
                raise ToolDeniedError("tool_call_not_available")
            if conversation.status != "active":
                raise ToolConflictError("conversation_inactive")
            return conversation, None

        return None, None

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
            with self._tx():
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
                self._validate_context_binding(principal, request.conversation_id, request.run_id)
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
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def decide_approval(
        self, principal: DevicePrincipal, approval_id: UUID, *, approve: bool
    ) -> ApprovalResponse:
        self._require_scope(principal, "approval.decide")
        is_expired = False
        is_parent_cancelled = False
        try:
            with self._tx():
                approval_meta = self.session.execute(
                    select(Approval.tool_call_id, Approval.owner_id).where(
                        Approval.id == approval_id
                    )
                ).first()
                if approval_meta is None or approval_meta[1] != principal.owner_id:
                    raise ApprovalError("approval_not_available")
                tool_call_id = approval_meta[0]

                # 1. Lock ToolCall FIRST
                call = self.session.scalar(
                    select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
                )
                if call is None or call.owner_id != principal.owner_id:
                    raise ApprovalError("approval_binding_invalid")
                # 2. Lock Approval SECOND
                approval = self.session.scalar(
                    select(Approval).where(Approval.id == approval_id).with_for_update()
                )
                if (
                    approval is None
                    or approval.owner_id != principal.owner_id
                    or approval.tool_call_id != call.id
                ):
                    raise ApprovalError("approval_binding_invalid")
                if approval.status != ApprovalStatus.PENDING.value:
                    raise ApprovalError("approval_not_pending")
                now = self.clock()
                if call.run_id is not None:
                    run = self.session.scalar(
                        select(AgentRun).where(AgentRun.id == call.run_id).with_for_update()
                    )
                    if run is not None and run.status in {
                        "cancelled",
                        "cancel_requested",
                        "failed",
                        "succeeded",
                    }:
                        call.status = ToolCallStatus.CANCELLED.value
                        call.reason_code = "parent_run_cancelled"
                        approval.status = ApprovalStatus.CANCELLED.value
                        self._audit(
                            call,
                            "tool.cancelled",
                            reason_code="parent_run_cancelled",
                            occurred_at=now,
                        )
                        self.session.flush()
                        is_parent_cancelled = True

                if is_parent_cancelled:
                    pass
                elif _aware(approval.expires_at) <= _aware(now):
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
                    is_expired = True
                else:
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
                    response = self._approval_response(approval)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise
        if is_parent_cancelled:
            raise ToolDeniedError("parent_run_cancelled")
        if is_expired:
            raise ApprovalError("approval_expired")
        return response

    def execute_tool_call(
        self,
        principal: DevicePrincipal,
        tool_call_id: UUID,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> ToolObservation:
        """Atomically consume authority, then execute only the typed bound request."""

        now = self.clock()
        is_expired = False
        is_parent_cancelled = False
        with self._tx():
            # 1. Lock ToolCall FIRST
            call = self.session.scalar(
                select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
            )
            if (
                call is None
                or call.owner_id != principal.owner_id
                or call.device_id != principal.device_id
            ):
                raise ToolDeniedError("tool_call_not_available")

            # Check terminal states
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

            # 2. Resolve descriptor
            descriptor = self.registry.resolve(call.tool_name, call.tool_version)
            if (
                call.tool_name != descriptor.name
                or call.tool_version != descriptor.version
                or call.risk_level != descriptor.risk_level.value
            ):
                raise ToolDeniedError("descriptor_binding_mismatch")
            if call.policy_version != "phase8-v1":
                raise ToolDeniedError("policy_version_mismatch")

            # Revalidate current approval policy requirement
            if (
                descriptor.risk_level in {RiskLevel.CONSEQUENTIAL, RiskLevel.CRITICAL}
                or descriptor.approval_policy is ApprovalPolicy.EXACT_OWNER
            ) and call.approval_id is None:
                raise ApprovalError("approval_required_by_current_policy")

            # Check argument digest if arguments provided
            if arguments is not None:
                validated = self.registry.validate_arguments(descriptor, arguments)
                if argument_digest(validated) != call.argument_digest:
                    raise ToolConflictError("argument_binding_mismatch")

            if call.status != ToolCallStatus.APPROVED.value:
                raise ApprovalError("execution_not_approved")

            # 3. Check Owner & Device active state
            owner = self.session.scalar(select(Owner).where(Owner.id == principal.owner_id))
            if owner is None or owner.status != "active":
                raise ToolDeniedError("owner_not_available")

            device = self.session.scalar(
                select(Device)
                .where(
                    Device.id == principal.device_id,
                    Device.owner_id == principal.owner_id,
                )
                .with_for_update()
            )
            if device is None or device.status != "active":
                raise ToolDeniedError("device_not_available")

            # 4. Check request scopes
            if descriptor.required_request_scopes - principal.scopes:
                raise ToolDeniedError("scope_missing")

            # 5. Check device capabilities
            if descriptor.required_device_capabilities:
                caps = set(
                    self.session.scalars(
                        select(DeviceCapability.capability).where(
                            DeviceCapability.device_id == principal.device_id
                        )
                    )
                )
                if not descriptor.required_device_capabilities.issubset(caps):
                    raise ToolDeniedError("capability_missing")

            # 6. Check tool enabled & not forbidden
            if not descriptor.enabled:
                raise ToolDeniedError("tool_disabled")
            if (
                descriptor.risk_level is RiskLevel.FORBIDDEN_AUTONOMOUS
                or descriptor.sandbox_policy is SandboxPolicy.FORBIDDEN
            ):
                raise ToolDeniedError("forbidden_autonomous")

            # 7. Check target availability
            state = self.availability(descriptor)
            if state is not AvailabilityState.AVAILABLE:
                raise ToolDeniedError(f"availability_{state.value}")

            # 8. Revalidate parent AgentRun / conversation / session state
            if call.run_id is not None:
                run = self.session.scalar(
                    select(AgentRun).where(AgentRun.id == call.run_id).with_for_update()
                )
                if run is None:
                    raise ToolDeniedError("parent_run_not_available")
                session_row = self.session.scalar(
                    select(ConversationSession)
                    .where(ConversationSession.id == run.session_id)
                    .with_for_update()
                )
                if (
                    session_row is None
                    or session_row.owner_id != principal.owner_id
                    or (
                        session_row.device_id != principal.device_id
                        and run.request_device_id != principal.device_id
                    )
                    or session_row.status != "active"
                ):
                    raise ToolDeniedError("session_not_available")
                conv_row = self.session.scalar(
                    select(Conversation).where(Conversation.id == run.conversation_id)
                )
                if (
                    conv_row is None
                    or conv_row.owner_id != principal.owner_id
                    or conv_row.status != "active"
                ):
                    raise ToolDeniedError("conversation_not_available")
                if run.status in {"cancelled", "cancel_requested", "failed", "succeeded"}:
                    call.status = ToolCallStatus.CANCELLED.value
                    call.reason_code = "parent_run_cancelled"
                    self._audit(
                        call,
                        "tool.cancelled",
                        reason_code="parent_run_cancelled",
                        occurred_at=now,
                    )
                    is_parent_cancelled = True
                if call.conversation_id is not None and run.conversation_id != call.conversation_id:
                    raise ToolConflictError("conversation_run_mismatch")

            if call.conversation_id is not None and call.run_id is None:
                conv_row = self.session.scalar(
                    select(Conversation).where(Conversation.id == call.conversation_id)
                )
                if (
                    conv_row is None
                    or conv_row.owner_id != principal.owner_id
                    or conv_row.status != "active"
                ):
                    raise ToolDeniedError("conversation_not_available")

            # 9. Lock and validate Approval SECOND (if approval-backed)
            if not is_parent_cancelled and call.approval_id is not None:
                approval = self.session.scalar(
                    select(Approval).where(Approval.id == call.approval_id).with_for_update()
                )
                if approval is None:
                    raise ApprovalError("approval_binding_invalid")
                if (
                    approval.owner_id != call.owner_id
                    or approval.requesting_device_id != call.device_id
                    or approval.tool_name != call.tool_name
                    or approval.tool_version != call.tool_version
                    or approval.risk_level != call.risk_level
                    or approval.argument_digest != call.argument_digest
                    or approval.policy_version != call.policy_version
                    or approval.tool_call_id != call.id
                ):
                    raise ApprovalError("approval_binding_invalid")
                if approval.status != ApprovalStatus.APPROVED.value:
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
                    is_expired = True
                else:
                    approval.status = ApprovalStatus.CONSUMED.value
                    approval.consumed_at = now

            if is_parent_cancelled or is_expired:
                pass  # will raise error outside transaction
            else:
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

        if is_parent_cancelled:
            raise ToolDeniedError("parent_run_cancelled")
        if is_expired:
            raise ApprovalError("approval_expired")

        try:
            raw = self.executor.execute(request)
        except Exception as error:
            now_exc = self.clock()
            with self._tx():
                call_row = self.session.scalar(
                    select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
                )
                if call_row is not None:
                    call_row.status = ToolCallStatus.FAILED.value
                    call_row.completed_at = now_exc
                    call_row.failure_code = "executor_uncertain_outcome"
                    self.session.add(
                        ToolObservationRow(
                            tool_call_id=call_row.id,
                            status=ToolObservationStatus.FAILED.value,
                            output_json={"error": "executor_uncertain_outcome"},
                            verification_json={"verified": False, "uncertain_outcome": True},
                            failure_code="executor_uncertain_outcome",
                            observed_at=now_exc,
                        )
                    )
                    self._audit(
                        call_row,
                        "tool.failed",
                        reason_code="executor_uncertain_outcome",
                        occurred_at=now_exc,
                    )
            raise ToolPlatformError(
                "executor_uncertain_outcome",
                "executor raised unexpected exception",
            ) from error

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
        with self._tx():
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
        with self._tx():
            # 1. Lock ToolCall FIRST
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
                ToolCallStatus.EXPIRED.value,
                ToolCallStatus.REJECTED.value,
                ToolCallStatus.DENIED.value,
            }:
                return self._response(call, replayed=True)
            call.status = ToolCallStatus.CANCELLED.value
            call.reason_code = "caller_cancelled"
            # 2. Lock Approval SECOND
            if call.approval_id is not None:
                approval = self.session.scalar(
                    select(Approval).where(Approval.id == call.approval_id).with_for_update()
                )
                if approval is not None and approval.status in {
                    ApprovalStatus.PENDING.value,
                    ApprovalStatus.APPROVED.value,
                }:
                    approval.status = ApprovalStatus.CANCELLED.value
            self._audit(call, "tool.cancelled", reason_code="caller_cancelled", occurred_at=now)
            return self._response(call, replayed=False)

    def expire_pending(self) -> int:
        now = self.clock()
        with self._tx():
            candidates = list(
                self.session.execute(
                    select(Approval.id, Approval.tool_call_id)
                    .where(
                        Approval.status == ApprovalStatus.PENDING.value,
                        Approval.expires_at <= now,
                    )
                    .order_by(Approval.tool_call_id)
                ).all()
            )
        count = 0
        for approval_id, tool_call_id in candidates:
            with self._tx():
                call = self.session.scalar(
                    select(ToolCall).where(ToolCall.id == tool_call_id).with_for_update()
                )
                approval = self.session.scalar(
                    select(Approval).where(Approval.id == approval_id).with_for_update()
                )
                if (
                    approval is not None
                    and approval.status == ApprovalStatus.PENDING.value
                    and _aware(approval.expires_at) <= _aware(now)
                ):
                    approval.status = ApprovalStatus.EXPIRED.value
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
        with self._tx():
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
        with self._tx():
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
        with self._tx():
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

    def reconcile_stale_executing(self, *, max_age_seconds: float = 0.0) -> int:
        """Reconcile any orphaned/stale executing calls into explicit failed state."""

        now = self.clock()
        reconciled_count = 0
        with self._tx():
            stale_calls = list(
                self.session.scalars(
                    select(ToolCall)
                    .where(ToolCall.status == ToolCallStatus.EXECUTING.value)
                    .with_for_update()
                )
            )
            for call in stale_calls:
                call.status = ToolCallStatus.FAILED.value
                call.completed_at = now
                call.failure_code = "executor_uncertain_outcome"
                call.reason_code = "stale_execution_reconciled"
                self.session.add(
                    ToolObservationRow(
                        tool_call_id=call.id,
                        status=ToolObservationStatus.FAILED.value,
                        output_json={"error": "stale_execution_reconciled"},
                        verification_json={
                            "verified": False,
                            "uncertain_outcome": True,
                            "reconciled_after_stale": True,
                        },
                        failure_code="executor_uncertain_outcome",
                        observed_at=now,
                    )
                )
                self._audit(
                    call,
                    "tool.failed",
                    reason_code="stale_execution_reconciled",
                    occurred_at=now,
                )
                reconciled_count += 1
        return reconciled_count

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
        if (
            descriptor.risk_level is RiskLevel.FORBIDDEN_AUTONOMOUS
            or descriptor.sandbox_policy is SandboxPolicy.FORBIDDEN
        ):
            return PermissionResult(PermissionDecisionKind.DENY, "forbidden_autonomous")
        if descriptor.risk_level in {RiskLevel.CONSEQUENTIAL, RiskLevel.CRITICAL}:
            if descriptor.approval_policy is not ApprovalPolicy.EXACT_OWNER:
                return PermissionResult(PermissionDecisionKind.DENY, "invalid_risk_approval_policy")
            return PermissionResult(
                PermissionDecisionKind.REQUIRE_APPROVAL, "owner_approval_required"
            )
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
        if (self.session.scalar(query) or 0) > self.MAX_APPROVALS_PER_RUN:
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
            self._validate_context_binding(principal, None, run_id)
            return
        device = self.session.scalar(
            select(Device)
            .where(
                Device.id == principal.device_id,
                Device.owner_id == principal.owner_id,
            )
            .with_for_update()
        )
        if device is None or device.status != "active":
            raise ToolDeniedError("device_not_available")

    def _require_scope(self, principal: DevicePrincipal, scope: str) -> None:
        if scope not in principal.scopes:
            raise ToolDeniedError("scope_missing")

    def _find_idempotent(self, principal: DevicePrincipal, name: str, key: str) -> ToolCall | None:
        with self._tx():
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
        with self._tx():
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
        self._emit_websocket_lifecycle(call, event, approval_id)

    def _emit_websocket_lifecycle(
        self, call: ToolCall, event_type: str, approval_id: UUID | None
    ) -> None:
        """Project redacted tool lifecycle facts into the existing Phase 7 stream."""

        if call.run_id is None:
            return
        run = self.session.scalar(select(AgentRun).where(AgentRun.id == call.run_id))
        if run is None:
            return
        session = self.session.scalar(
            select(ConversationSession)
            .where(
                ConversationSession.id == run.session_id,
                ConversationSession.owner_id == call.owner_id,
            )
            .with_for_update()
        )
        if session is None or session.status != "active":
            return
        if session.device_id != call.device_id and run.request_device_id != call.device_id:
            return
        latest = self.session.scalar(
            select(func.max(RunEvent.sequence)).where(RunEvent.session_id == session.id)
        )
        self.session.add(
            RunEvent(
                conversation_id=run.conversation_id,
                session_id=session.id,
                run_id=run.id,
                sequence=(latest or 0) + 1,
                event_type=event_type,
                payload_json={
                    "tool_call_id": str(call.id),
                    "approval_id": None if approval_id is None else str(approval_id),
                    "status": call.status,
                    "argument_digest": call.argument_digest,
                },
                occurred_at=self.clock(),
            )
        )
        self.session.flush()

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
