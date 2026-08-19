from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from personal_ai_os.conversations.models import RunEvent
from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.db.base import Base
from personal_ai_os.identity.contracts import (
    PHASE_8_SCOPES,
    DevicePrincipal,
    EnrollmentGrant,
)
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.model_gateway.contracts import ToolProposal
from personal_ai_os.tools.agent_runtime import BoundedAgentToolRuntime
from personal_ai_os.tools.contracts import (
    ApprovalPolicy,
    ApprovalStatus,
    RiskLevel,
    SandboxPolicy,
    ToolCallRequest,
    ToolCallStatus,
    ToolObservationStatus,
)
from personal_ai_os.tools.errors import (
    ApprovalError,
    ToolBudgetError,
    ToolConflictError,
    ToolDeniedError,
    ToolPlatformError,
    ToolSchemaError,
)
from personal_ai_os.tools.registry import (
    ToolRegistry,
    argument_digest,
    default_registry,
    deterministic_preview,
)
from personal_ai_os.tools.service import ToolPlatformService


@pytest.fixture
def sqlite_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def identity(sqlite_session: Session) -> tuple[Session, Any]:
    service = IdentityService(sqlite_session)
    owner = service.bootstrap_owner("Synthetic Phase 8 owner")
    enrollment = service.create_enrollment(
        EnrollmentGrant(
            owner_id=owner.id,
            display_name="Synthetic Phase 8 device",
            device_kind="windows_client",
            platform="windows",
            scopes=sorted(PHASE_8_SCOPES),
        )
    )
    issued = service.redeem_enrollment(enrollment.code)
    return sqlite_session, service.authenticate(issued.raw)


def test_registry_is_static_strict_and_preview_is_deterministic() -> None:
    registry = default_registry()
    descriptor = registry.resolve("phase8.status.read", 1)
    assert descriptor.risk_level.value == "read"
    assert registry.validate_arguments(descriptor, {"resource": "platform"}) == {
        "resource": "platform"
    }
    with pytest.raises(ToolSchemaError):
        registry.validate_arguments(descriptor, {"resource": "platform", "extra": True})
    with pytest.raises(ToolSchemaError):
        registry.validate_arguments(descriptor, {"resource": 1})
    assert argument_digest({"b": 2, "a": 1}) == argument_digest({"a": 1, "b": 2})
    preview = deterministic_preview(descriptor, {"resource": "platform", "api_token": "secret"})
    assert preview["arguments"]["api_token"] == "[REDACTED]"
    with pytest.raises(ToolPlatformError):
        registry.resolve("phase8.status.read", 2)


def test_allow_replay_and_typed_success(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    request = ToolCallRequest(
        name="phase8.status.read",
        version=1,
        arguments={"resource": "platform"},
        idempotency_key="phase8-status-000001",
    )
    first = service.request_tool(principal, request)
    replay = service.request_tool(principal, request)
    assert first.status is ToolCallStatus.APPROVED
    assert replay.replayed is True
    observation = service.execute_tool_call(principal, first.id)
    assert observation.status is ToolObservationStatus.SUCCEEDED
    assert service.execute_tool_call(principal, first.id).status is ToolObservationStatus.SUCCEEDED


def test_approval_is_exactly_bound_and_consumed(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    response = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "synthetic"},
            idempotency_key="phase8-approval-0001",
        ),
    )
    assert response.status is ToolCallStatus.AWAITING_APPROVAL
    assert response.approval_id is not None
    with pytest.raises(ToolConflictError):
        service.execute_tool_call(principal, response.id, arguments={"message": "changed"})
    decision = service.decide_approval(principal, response.approval_id, approve=True)
    assert decision.status is ApprovalStatus.APPROVED
    assert (
        service.execute_tool_call(principal, response.id).status is ToolObservationStatus.SUCCEEDED
    )
    with pytest.raises(ApprovalError):
        service.decide_approval(principal, response.approval_id, approve=False)


@pytest.mark.parametrize("name", ["phase8.forbidden.shell", "phase8.offline.read"])
def test_forbidden_and_unavailable_never_execute(
    sqlite_session: Session, identity: tuple[Session, Any], name: str
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    response = service.request_tool(
        principal,
        ToolCallRequest(name=name, version=1, arguments={}, idempotency_key=f"deny-{name}"),
    )
    assert response.status is ToolCallStatus.DENIED


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("phase8.invalid.output", "output_schema_invalid"),
        ("phase8.verification.fail", "verification_failed"),
    ],
)
def test_output_and_verification_failures_are_not_success(
    sqlite_session: Session, identity: tuple[Session, Any], name: str, expected: str
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    response = service.request_tool(
        principal,
        ToolCallRequest(name=name, version=1, arguments={}, idempotency_key=f"fail-{name}"),
    )
    observation = service.execute_tool_call(principal, response.id)
    assert observation.status is ToolObservationStatus.FAILED
    assert observation.failure_code == expected


def test_cancel_and_budget_are_fail_closed(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    requests = [
        service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key=f"phase8-budget-{index:02d}",
            ),
        )
        for index in range(4)
    ]
    for request in requests[:3]:
        assert (
            service.execute_tool_call(principal, request.id).status
            is ToolObservationStatus.SUCCEEDED
        )
    with pytest.raises(ToolBudgetError):
        service.execute_tool_call(principal, requests[3].id)
    cancelled = service.cancel_tool_call(principal, requests[3].id)
    assert cancelled.status is ToolCallStatus.CANCELLED


def test_bounded_agent_runtime_keeps_model_proposals_as_data(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    result = BoundedAgentToolRuntime(service).submit_proposals(
        principal,
        (ToolProposal(name="phase8.status.read", arguments={"resource": "platform"}),),
        idempotency_prefix="agent-loop-0001",
    )
    assert result.proposals_seen == 1
    assert result.requests[0].status is ToolCallStatus.APPROVED
    assert result.paused_for_approval is False


def test_bound_run_projects_redacted_tool_lifecycle_to_websocket_events(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    conversation_service = ConversationService(sqlite_session)
    conversation = conversation_service.create_conversation(principal, "Synthetic event thread")
    conversation_session = conversation_service.create_session(principal, conversation.id)
    submission = conversation_service.submit_message(
        principal,
        conversation_session.id,
        uuid4(),
        "synthetic event trigger",
        correlation_id="phase8-event-test",
    )
    service = ToolPlatformService(sqlite_session)
    call = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="phase8-websocket-event-1",
            conversation_id=conversation.id,
            run_id=submission.run.id,
        ),
    )
    service.execute_tool_call(principal, call.id)
    events = list(
        sqlite_session.scalars(
            select(RunEvent).where(RunEvent.run_id == submission.run.id).order_by(RunEvent.sequence)
        )
    )
    assert [event.event_type for event in events][-2:] == ["tool.started", "tool.succeeded"]
    assert all("arguments" not in event.payload_json for event in events)


def test_context_binding_rejects_foreign_and_mismatched_runs(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal1 = identity
    identity_service = IdentityService(sqlite_session)
    grant2 = identity_service.create_enrollment(
        EnrollmentGrant(
            owner_id=principal1.owner_id,
            display_name="Synthetic Phase 8 device 2",
            device_kind="windows_client",
            platform="windows",
            scopes=sorted(PHASE_8_SCOPES),
        )
    )
    issued2 = identity_service.redeem_enrollment(grant2.code)
    principal2 = identity_service.authenticate(issued2.raw)

    foreign_principal = DevicePrincipal(
        owner_id=uuid4(),
        device_id=uuid4(),
        credential_id=uuid4(),
        scopes=frozenset(PHASE_8_SCOPES),
    )

    conv_service = ConversationService(sqlite_session)
    conv1 = conv_service.create_conversation(principal1, "Owner 1 thread")
    sess1 = conv_service.create_session(principal1, conv1.id)
    sub1 = conv_service.submit_message(
        principal1, sess1.id, uuid4(), "prompt 1", correlation_id="c1"
    )

    conv2 = conv_service.create_conversation(principal2, "Owner 1 device 2 thread")
    sess2 = conv_service.create_session(principal2, conv2.id)
    sub2 = conv_service.submit_message(
        principal2, sess2.id, uuid4(), "prompt 2", correlation_id="c2"
    )

    service = ToolPlatformService(sqlite_session)

    # 1. Foreign-owner principal request on run_id -> denied
    with pytest.raises(ToolPlatformError):
        service.request_tool(
            foreign_principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="foreign-run-0001",
                run_id=sub1.run.id,
            ),
        )

    # 2. Foreign-owner principal request on conversation_id -> denied
    with pytest.raises(ToolPlatformError):
        service.request_tool(
            foreign_principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="foreign-conv-0001",
                conversation_id=conv1.id,
            ),
        )

    # 3. Requesting device mismatch on session -> denied
    with pytest.raises(ToolPlatformError):
        service.request_tool(
            principal1,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="device-mismatch-0001",
                run_id=sub2.run.id,
            ),
        )

    # 4. Conversation_id mismatching run_id -> conflict
    conv1_other = conv_service.create_conversation(principal1, "Owner 1 second thread")
    with pytest.raises(ToolConflictError):
        service.request_tool(
            principal1,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="mismatch-run-conv-0002",
                conversation_id=conv1_other.id,
                run_id=sub1.run.id,
            ),
        )

    # 5. Foreign run receives zero RunEvents
    events_run2 = list(
        sqlite_session.scalars(select(RunEvent).where(RunEvent.run_id == sub2.run.id))
    )
    assert not any("tool" in event.event_type for event in events_run2)


def test_durable_expiry_persists_expired_state_and_audit(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from datetime import UTC, datetime, timedelta

    from personal_ai_os.tools.models import Approval, AuditEvent, ToolCall

    _, principal = identity
    fixed_time = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    current_time = fixed_time

    def clock() -> datetime:
        return current_time

    service = ToolPlatformService(sqlite_session, clock=clock)
    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "expiry test"},
            idempotency_key="expiry-test-0001",
        ),
    )
    assert resp.approval_id is not None

    # Advance clock past TTL (10 minutes for consequential)
    current_time = fixed_time + timedelta(minutes=15)

    # Direct decide on expired approval
    with pytest.raises(ApprovalError) as exc_info:
        service.decide_approval(principal, resp.approval_id, approve=True)
    assert exc_info.value.code == "approval_expired"

    # Prove durable state in DB (transaction was NOT rolled back!)
    with sqlite_session.begin():
        call = sqlite_session.get(ToolCall, resp.id)
        approval = sqlite_session.get(Approval, resp.approval_id)
        assert call is not None and call.status == ToolCallStatus.EXPIRED.value
        assert approval is not None and approval.status == ApprovalStatus.EXPIRED.value

        audits = list(
            sqlite_session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tool_call_id == resp.id,
                    AuditEvent.event_type == "approval.expired",
                )
            )
        )
        assert len(audits) >= 1

    # Execute on expired approval also fails closed and keeps durable expired state
    current_time = fixed_time
    resp2 = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "expiry test 2"},
            idempotency_key="expiry-test-0002",
        ),
    )
    assert resp2.approval_id is not None
    service.decide_approval(principal, resp2.approval_id, approve=True)
    # Advance time after decision
    current_time = fixed_time + timedelta(minutes=15)
    with pytest.raises(ApprovalError) as exc_info2:
        service.execute_tool_call(principal, resp2.id)
    assert exc_info2.value.code == "approval_expired"

    with sqlite_session.begin():
        call2 = sqlite_session.get(ToolCall, resp2.id)
        approval2 = sqlite_session.get(Approval, resp2.approval_id)
        assert call2 is not None and call2.status == ToolCallStatus.EXPIRED.value
        assert approval2 is not None and approval2.status == ApprovalStatus.EXPIRED.value


def test_execution_revalidates_authority_and_binding(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from personal_ai_os.identity.contracts import DevicePrincipal
    from personal_ai_os.identity.models import Device
    from personal_ai_os.tools.contracts import AvailabilityState

    _, principal = identity
    service = ToolPlatformService(sqlite_session)

    # 1. Authority revalidation: device revoked
    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="reval-device-0001",
        ),
    )
    with sqlite_session.begin():
        device = sqlite_session.get(Device, principal.device_id)
        assert device is not None
        device.status = "revoked"

    with pytest.raises(ToolPlatformError):
        service.execute_tool_call(principal, resp.id)

    # Restore device status
    with sqlite_session.begin():
        device = sqlite_session.get(Device, principal.device_id)
        assert device is not None
        device.status = "active"

    # 2. Scope missing at execution time
    resp_scope = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="reval-scope-0001",
        ),
    )
    principal_no_scope = DevicePrincipal(
        owner_id=principal.owner_id,
        device_id=principal.device_id,
        credential_id=principal.credential_id,
        scopes=frozenset({"device.self.read"}),
    )
    with pytest.raises(ToolPlatformError):
        service.execute_tool_call(principal_no_scope, resp_scope.id)

    # 3. Availability offline at execution time
    resp_avail = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="reval-avail-0001",
        ),
    )
    service_offline = ToolPlatformService(
        sqlite_session,
        availability=lambda _: AvailabilityState.OFFLINE,
    )
    with pytest.raises(ToolPlatformError):
        service_offline.execute_tool_call(principal, resp_avail.id)


def test_executor_unexpected_exception_does_not_strand_executing(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from personal_ai_os.tools.models import AuditEvent, ToolCall, ToolObservationRow

    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.uncertain.outcome",
            version=1,
            arguments={},
            idempotency_key="uncertain-crash-0001",
        ),
    )
    assert resp.status is ToolCallStatus.APPROVED

    with pytest.raises(ToolPlatformError) as exc_info:
        service.execute_tool_call(principal, resp.id)
    assert exc_info.value.code == "executor_uncertain_outcome"

    # Prove durable row state in DB: NOT left in 'executing'
    with sqlite_session.begin():
        call = sqlite_session.get(ToolCall, resp.id)
        assert call is not None
        assert call.status == ToolCallStatus.FAILED.value
        assert call.failure_code == "executor_uncertain_outcome"

        obs = sqlite_session.scalar(
            select(ToolObservationRow).where(ToolObservationRow.tool_call_id == resp.id)
        )
        assert obs is not None
        assert obs.status == ToolObservationStatus.FAILED.value
        assert obs.failure_code == "executor_uncertain_outcome"
        assert obs.verification_json.get("uncertain_outcome") is True

        audit = sqlite_session.scalar(
            select(AuditEvent).where(
                AuditEvent.tool_call_id == resp.id,
                AuditEvent.event_type == "tool.failed",
            )
        )
        assert audit is not None
        assert audit.reason_code == "executor_uncertain_outcome"

    # Subsequent replay returns the saved failed observation and does not blind-retry
    replay_obs = service.execute_tool_call(principal, resp.id)
    assert replay_obs.status is ToolObservationStatus.FAILED
    assert replay_obs.failure_code == "executor_uncertain_outcome"


def test_risk_level_is_authoritative_and_descriptor_validation() -> None:
    from pydantic import BaseModel

    from personal_ai_os.tools.registry import _descriptor

    class DummyArgs(BaseModel):
        pass

    class DummyOut(BaseModel):
        pass

    # Consequential + NONE -> rejected at construction
    with pytest.raises(
        ValueError, match="consequential and critical tools require exact_owner approval"
    ):
        _descriptor(
            "test.bad.consequential",
            "desc",
            DummyArgs,
            DummyOut,
            RiskLevel.CONSEQUENTIAL,
            approval=ApprovalPolicy.NONE,
        )

    # Critical + NONE -> rejected at construction
    with pytest.raises(
        ValueError, match="consequential and critical tools require exact_owner approval"
    ):
        _descriptor(
            "test.bad.critical",
            "desc",
            DummyArgs,
            DummyOut,
            RiskLevel.CRITICAL,
            approval=ApprovalPolicy.NONE,
        )

    # Forbidden + EXACT_OWNER -> valid descriptor, but permission fails closed to DENY
    desc_forbidden = _descriptor(
        "test.forbidden",
        "desc",
        DummyArgs,
        DummyOut,
        RiskLevel.FORBIDDEN_AUTONOMOUS,
        approval=ApprovalPolicy.EXACT_OWNER,
        sandbox=SandboxPolicy.FORBIDDEN,
    )
    # Read + EXACT_OWNER -> valid descriptor, requires approval
    desc_read_approval = _descriptor(
        "test.read.approval",
        "desc",
        DummyArgs,
        DummyOut,
        RiskLevel.READ,
        approval=ApprovalPolicy.EXACT_OWNER,
    )
    # Reversible + EXACT_OWNER -> valid descriptor, requires approval
    desc_rev_approval = _descriptor(
        "test.rev.approval",
        "desc",
        DummyArgs,
        DummyOut,
        RiskLevel.REVERSIBLE,
        approval=ApprovalPolicy.EXACT_OWNER,
    )

    reg = ToolRegistry((desc_forbidden, desc_read_approval, desc_rev_approval))
    assert reg.resolve("test.forbidden", 1).risk_level == RiskLevel.FORBIDDEN_AUTONOMOUS
    assert reg.resolve("test.read.approval", 1).approval_policy == ApprovalPolicy.EXACT_OWNER


def test_parent_run_cancellation_denies_execution_and_decision(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from personal_ai_os.conversations.models import AgentRun
    from personal_ai_os.tools.models import ToolCall

    _, principal = identity
    conv_service = ConversationService(sqlite_session)
    conv = conv_service.create_conversation(principal, "Parent cancel test")
    sess = conv_service.create_session(principal, conv.id)
    sub = conv_service.submit_message(
        principal,
        sess.id,
        uuid4(),
        "start parent run",
        correlation_id="parent-cancel-test",
    )
    run_id = sub.run.id
    service = ToolPlatformService(sqlite_session)

    # 1. Consequential call with pending approval
    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "consequential action"},
            idempotency_key="parent-cancel-0001",
            conversation_id=conv.id,
            run_id=run_id,
        ),
    )
    assert resp.status is ToolCallStatus.AWAITING_APPROVAL
    assert resp.approval_id is not None

    # Cancel the parent AgentRun
    with sqlite_session.begin():
        run = sqlite_session.get(AgentRun, run_id)
        assert run is not None
        run.status = "cancelled"

    # Approving the call now must be denied and mark tool call / approval cancelled
    with pytest.raises(ToolDeniedError) as exc_info:
        service.decide_approval(principal, resp.approval_id, approve=True)
    assert exc_info.value.code == "parent_run_cancelled"

    with sqlite_session.begin():
        call = sqlite_session.get(ToolCall, resp.id)
        assert call is not None
        assert call.status == ToolCallStatus.CANCELLED.value
        assert call.reason_code == "parent_run_cancelled"

    # 2. Reversible/Read call approved while run was active, but run cancelled before execution
    conv2 = conv_service.create_conversation(principal, "Parent cancel test 2")
    sess2 = conv_service.create_session(principal, conv2.id)
    sub2 = conv_service.submit_message(
        principal,
        sess2.id,
        uuid4(),
        "start parent run 2",
        correlation_id="parent-cancel-test-2",
    )
    run_id_2 = sub2.run.id

    resp2 = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="parent-cancel-0002",
            conversation_id=conv2.id,
            run_id=run_id_2,
        ),
    )
    assert resp2.status is ToolCallStatus.APPROVED

    with sqlite_session.begin():
        run2 = sqlite_session.get(AgentRun, run_id_2)
        assert run2 is not None
        run2.status = "cancel_requested"

    # Execution must fail and cancel the tool call
    with pytest.raises(ToolDeniedError) as exc_info2:
        service.execute_tool_call(principal, resp2.id)
    assert exc_info2.value.code == "parent_run_cancelled"

    with sqlite_session.begin():
        call2 = sqlite_session.get(ToolCall, resp2.id)
        assert call2 is not None
        assert call2.status == ToolCallStatus.CANCELLED.value


def test_execution_time_policy_revalidation_denies_stricter_descriptor(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from personal_ai_os.tools.registry import _descriptor
    from personal_ai_os.tools.schemas import StatusArguments, StatusOutput

    _, principal = identity
    service = ToolPlatformService(sqlite_session)

    # Stage call with normal status read (Risk READ, Approval NONE)
    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="stricter-policy-0001",
        ),
    )
    assert resp.status is ToolCallStatus.APPROVED
    assert resp.approval_id is None

    # Replace service registry with a stricter descriptor that requires approval
    stricter_desc = _descriptor(
        "phase8.status.read",
        "Read a synthetic status requiring owner approval.",
        StatusArguments,
        StatusOutput,
        RiskLevel.READ,
        approval=ApprovalPolicy.EXACT_OWNER,
    )
    service.registry = ToolRegistry((stricter_desc,))

    # Execution must fail because unapproved call does not satisfy new EXACT_OWNER policy
    with pytest.raises(ApprovalError) as exc_info:
        service.execute_tool_call(principal, resp.id)
    assert exc_info.value.code == "approval_required_by_current_policy"


def test_uncertain_executor_exception_redacts_raw_exception_text(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from personal_ai_os.tools.executor import SyntheticToolExecutor
    from personal_ai_os.tools.models import AuditEvent, ToolObservationRow

    _, principal = identity

    class LeakyCrashExecutor(SyntheticToolExecutor):
        def execute(self, request: Any) -> Any:
            raise RuntimeError(
                "crash with password=supersecret token=bearer_12345 "
                "Authorization=Bearer_abc private_key=pk_xyz"
            )

    service = ToolPlatformService(sqlite_session, executor=LeakyCrashExecutor())

    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.status.read",
            version=1,
            arguments={"resource": "platform"},
            idempotency_key="leaky-crash-0001",
        ),
    )
    assert resp.status is ToolCallStatus.APPROVED

    with pytest.raises(ToolPlatformError) as exc_info:
        service.execute_tool_call(principal, resp.id)

    # Exception message must NOT contain leaked secrets
    error_msg = str(exc_info.value)
    assert "supersecret" not in error_msg
    assert "bearer_12345" not in error_msg
    assert "Bearer_abc" not in error_msg
    assert "pk_xyz" not in error_msg

    with sqlite_session.begin():
        obs = sqlite_session.scalar(
            select(ToolObservationRow).where(ToolObservationRow.tool_call_id == resp.id)
        )
        assert obs is not None
        assert "supersecret" not in json.dumps(obs.output_json)
        assert "supersecret" not in json.dumps(obs.verification_json)
        assert obs.output_json.get("error") == "executor_uncertain_outcome"

        audit = sqlite_session.scalar(
            select(AuditEvent).where(
                AuditEvent.tool_call_id == resp.id,
                AuditEvent.event_type == "tool.failed",
            )
        )
        assert audit is not None
        assert "supersecret" not in json.dumps(audit.metadata_json)
        assert audit.reason_code == "executor_uncertain_outcome"


def test_exact_approval_preview_full_length_and_sensitive_tokens() -> None:
    from pydantic import BaseModel, Field

    from personal_ai_os.tools.registry import _descriptor, deterministic_preview

    class CustomAuthArgs(BaseModel):
        message: str = Field(max_length=250)
        api_key: str = Field(default="api-12345")
        private_key: str = Field(default="key-67890")
        session_cookie: str = Field(default="cookie-abcde")

    class DummyOut(BaseModel):
        pass

    desc = _descriptor(
        "custom.auth.tool",
        "desc",
        CustomAuthArgs,
        DummyOut,
        RiskLevel.CONSEQUENTIAL,
        approval=ApprovalPolicy.EXACT_OWNER,
    )

    long_msg = "A" * 199 + "Z"
    args = {
        "message": long_msg,
        "api_key": "my-secret-api-key",
        "private_key": "my-secret-private-key",
        "session_cookie": "my-secret-cookie",
    }

    preview = deterministic_preview(desc, args)
    # Complete 200-char message is preserved without generic 160-char truncation
    assert preview["arguments"]["message"] == long_msg
    assert len(preview["arguments"]["message"]) == 200
    assert preview["arguments"]["message"].endswith("Z")

    # Sensitive fields are redacted
    assert preview["arguments"]["api_key"] == "[REDACTED]"
    assert preview["arguments"]["private_key"] == "[REDACTED]"
    assert preview["arguments"]["session_cookie"] == "[REDACTED]"

    # Changing the last character changes preview and argument_digest
    args2 = dict(args)
    args2["message"] = "A" * 199 + "Y"
    preview2 = deterministic_preview(desc, args2)
    assert preview2["arguments"]["message"] == "A" * 199 + "Y"
    assert preview2["argument_digest"] != preview["argument_digest"]


def test_stale_executing_reconciliation_produces_uncertain_outcome_with_no_retry(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from datetime import UTC, datetime

    from personal_ai_os.tools.models import AuditEvent, ToolCall, ToolObservationRow

    _, principal = identity
    service = ToolPlatformService(sqlite_session)

    # Insert a stale executing call simulating process restart after side-effect execution
    call_id = uuid4()
    now = datetime.now(UTC)
    with sqlite_session.begin():
        sqlite_session.add(
            ToolCall(
                id=call_id,
                owner_id=principal.owner_id,
                device_id=principal.device_id,
                tool_name="phase8.consequential.echo",
                tool_version=1,
                arguments_json={"message": "stale action"},
                argument_digest="digest123",
                idempotency_key="stale-exec-0001",
                risk_level=RiskLevel.CONSEQUENTIAL.value,
                policy_version="phase8-v1",
                status=ToolCallStatus.EXECUTING.value,
                started_at=now,
                created_at=now,
            )
        )

    # Run reconciliation
    reconciled = service.reconcile_stale_executing()
    assert reconciled == 1

    with sqlite_session.begin():
        call = sqlite_session.get(ToolCall, call_id)
        assert call is not None
        assert call.status == ToolCallStatus.FAILED.value
        assert call.failure_code == "executor_uncertain_outcome"
        assert call.reason_code == "stale_execution_reconciled"

        obs = sqlite_session.scalar(
            select(ToolObservationRow).where(ToolObservationRow.tool_call_id == call_id)
        )
        assert obs is not None
        assert obs.status == ToolObservationStatus.FAILED.value
        assert obs.failure_code == "executor_uncertain_outcome"
        assert obs.verification_json.get("uncertain_outcome") is True
        assert obs.verification_json.get("reconciled_after_stale") is True

        audit = sqlite_session.scalar(
            select(AuditEvent).where(
                AuditEvent.tool_call_id == call_id,
                AuditEvent.event_type == "tool.failed",
            )
        )
        assert audit is not None
        assert audit.reason_code == "stale_execution_reconciled"

    # Subsequent execution returns the saved observation and never re-executes
    replay_obs = service.execute_tool_call(principal, call_id)
    assert replay_obs.status is ToolObservationStatus.FAILED
    assert replay_obs.failure_code == "executor_uncertain_outcome"


def test_live_db_scope_and_identity_revocation_denies_execution(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from personal_ai_os.identity.models import Device, DeviceScope, Owner
    from personal_ai_os.tools.contracts import ToolCallRequest, ToolCallStatus
    from personal_ai_os.tools.executor import SyntheticToolExecutor
    from personal_ai_os.tools.service import ToolPlatformService

    _, principal = identity

    class CountingExecutor(SyntheticToolExecutor):
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, req: Any) -> Any:
            self.calls += 1
            return super().execute(req)

    executor = CountingExecutor()
    service = ToolPlatformService(sqlite_session, executor=executor)

    # 1. Stage and approve a tool call
    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "valid call"},
            idempotency_key="scope-revocation-test-1",
        ),
    )
    assert resp.status is ToolCallStatus.AWAITING_APPROVAL
    appr = service.decide_approval(principal, resp.approval_id, approve=True)
    assert appr.status is ApprovalStatus.APPROVED

    # 2. Revoke "tool.request" scope from DB while keeping stale principal in-memory
    with sqlite_session.begin():
        sqlite_session.query(DeviceScope).filter(
            DeviceScope.device_id == principal.device_id,
            DeviceScope.scope == "tool.request",
        ).delete()

    with pytest.raises(ToolDeniedError) as exc_info:
        service.execute_tool_call(principal, resp.id)
    assert exc_info.value.code == "scope_missing"
    assert executor.calls == 0

    # 3. Restore scope: test device revoked
    with sqlite_session.begin():
        sqlite_session.add(DeviceScope(device_id=principal.device_id, scope="tool.request"))
        dev = sqlite_session.get(Device, principal.device_id)
        dev.status = "revoked"

    with pytest.raises(ToolDeniedError) as exc_info2:
        service.execute_tool_call(principal, resp.id)
    assert exc_info2.value.code == "device_not_available"

    # 4. Restore device: test owner disabled
    with sqlite_session.begin():
        dev = sqlite_session.get(Device, principal.device_id)
        dev.status = "active"
        owner = sqlite_session.get(Owner, principal.owner_id)
        owner.status = "disabled"

    with pytest.raises(ToolDeniedError) as exc_info3:
        service.execute_tool_call(principal, resp.id)
    assert exc_info3.value.code == "owner_not_available"

    # 5. Restore owner: execution succeeds
    with sqlite_session.begin():
        owner = sqlite_session.get(Owner, principal.owner_id)
        owner.status = "active"

    obs = service.execute_tool_call(principal, resp.id)
    assert obs.status is ToolObservationStatus.SUCCEEDED
    assert executor.calls == 1


def test_application_startup_tool_reconciliation_gate(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    from datetime import UTC, datetime

    from personal_ai_os.tools.models import ToolCall
    from personal_ai_os.tools.reconciliation import ToolReconciliationGate

    _, principal = identity
    # Stage an executing tool call
    call_id = uuid4()
    now = datetime.now(UTC)
    with sqlite_session.begin():
        sqlite_session.add(
            ToolCall(
                id=call_id,
                owner_id=principal.owner_id,
                device_id=principal.device_id,
                tool_name="phase8.consequential.echo",
                tool_version=1,
                arguments_json={"message": "gate test"},
                argument_digest="digest-gate-1",
                idempotency_key="gate-test-0001",
                risk_level=RiskLevel.CONSEQUENTIAL.value,
                policy_version="phase8-v1",
                status=ToolCallStatus.EXECUTING.value,
                started_at=now,
                created_at=now,
            )
        )

    # Test ToolReconciliationGate directly
    engine = sqlite_session.get_bind()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    gate = ToolReconciliationGate()
    assert not gate.ready
    assert gate.attempt(factory)
    assert gate.ready
    assert not gate.deferred

    with sqlite_session.begin():
        call = sqlite_session.get(ToolCall, call_id)
        assert call is not None
        assert call.status == ToolCallStatus.FAILED.value
        assert call.failure_code == "executor_uncertain_outcome"


def test_executor_unexpected_exception_cause_suppression_and_no_secret_leakage(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    import traceback

    from personal_ai_os.tools.contracts import ToolCallRequest
    from personal_ai_os.tools.models import AuditEvent, ToolObservationRow
    from personal_ai_os.tools.service import ToolPlatformService

    _, principal = identity

    secret_marker = "password=supersecret_auth_token_98765"

    class LeakyExecutor:
        def execute(self, req: Any) -> Any:
            raise RuntimeError(f"Crashing with secret {secret_marker}")

    service = ToolPlatformService(sqlite_session, executor=LeakyExecutor())

    resp = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "hello secret"},
            idempotency_key="secret-leakage-test-1",
        ),
    )
    assert resp.approval_id is not None
    service.decide_approval(principal, resp.approval_id, approve=True)

    with pytest.raises(ToolPlatformError) as exc_info:
        service.execute_tool_call(principal, resp.id)

    err = exc_info.value
    assert err.code == "executor_uncertain_outcome"
    assert err.__cause__ is None
    assert err.__suppress_context__ is True

    # Traceback formatting does not include secret marker
    formatted_tb = "".join(traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb))
    assert secret_marker not in formatted_tb
    assert str(err) == "executor raised unexpected exception"

    # Verify secret is not in observation row or audit row
    with sqlite_session.begin():
        obs = sqlite_session.scalar(
            select(ToolObservationRow).where(ToolObservationRow.tool_call_id == resp.id)
        )
        assert obs is not None
        assert secret_marker not in json.dumps(obs.output_json)
        assert secret_marker not in json.dumps(obs.verification_json)

        audit = sqlite_session.scalar(
            select(AuditEvent).where(
                AuditEvent.tool_call_id == resp.id,
                AuditEvent.event_type == "tool.failed",
            )
        )
        assert audit is not None
        assert secret_marker not in json.dumps(audit.metadata_json)
