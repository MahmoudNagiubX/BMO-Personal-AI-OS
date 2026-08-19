from __future__ import annotations

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
    ApprovalStatus,
    ToolCallRequest,
    ToolCallStatus,
    ToolObservationStatus,
)
from personal_ai_os.tools.errors import (
    ApprovalError,
    ToolBudgetError,
    ToolConflictError,
    ToolPlatformError,
    ToolSchemaError,
)
from personal_ai_os.tools.registry import argument_digest, default_registry, deterministic_preview
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
