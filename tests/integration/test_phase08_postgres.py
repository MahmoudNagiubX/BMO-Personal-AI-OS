import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.identity.contracts import PHASE_8_SCOPES, DevicePrincipal, EnrollmentGrant
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.tools.contracts import (
    ApprovalPolicy,
    ApprovalStatus,
    RiskLevel,
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
)
from personal_ai_os.tools.executor import SyntheticToolExecutor
from personal_ai_os.tools.models import Approval, AuditEvent, ToolCall, ToolObservationRow
from personal_ai_os.tools.registry import ToolRegistry, _descriptor
from personal_ai_os.tools.schemas import StatusArguments, StatusOutput
from personal_ai_os.tools.service import ToolPlatformService

pytestmark = pytest.mark.integration


@pytest.fixture
def test_database_url() -> str:
    value = os.environ.get("BMO_TEST_DATABASE_URL")
    if not value:
        pytest.skip("BMO_TEST_DATABASE_URL is not set")
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+psycopg" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("integration tests only accept a localhost PostgreSQL URL")
    return value


def _provision(factory: sessionmaker) -> tuple[UUID, DevicePrincipal]:
    with factory() as session:
        identity = IdentityService(session)
        owner = identity.bootstrap_owner("Synthetic Phase 8 PostgreSQL owner")
        enrollment = identity.create_enrollment(
            EnrollmentGrant(
                owner_id=owner.id,
                display_name="Synthetic Phase 8 PostgreSQL client",
                device_kind="windows_client",
                platform="windows",
                scopes=sorted(PHASE_8_SCOPES),
            )
        )
        issued = identity.redeem_enrollment(enrollment.code)
        return owner.id, identity.authenticate(issued.raw)


@pytest.fixture
def database(test_database_url: str) -> tuple[object, sessionmaker, DevicePrincipal]:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE owners CASCADE"))
    _, principal = _provision(factory)
    try:
        yield engine, factory, principal
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_postgresql_same_idempotency_key_has_one_insert_and_replay(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    engine, factory, principal = database
    del engine
    barrier = Barrier(2)
    request = ToolCallRequest(
        name="phase8.status.read",
        version=1,
        arguments={"resource": "platform"},
        idempotency_key="pg-same-key-000001",
    )

    def submit(_: int) -> bool:
        with factory() as session:
            barrier.wait(timeout=5)
            return ToolPlatformService(session).request_tool(principal, request).replayed

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, range(2)))
    assert sorted(outcomes) == [False, True]


def test_postgresql_different_arguments_same_key_conflict(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    service = ToolPlatformService(factory())
    try:
        service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.reversible.set",
                version=1,
                arguments={"value": 1},
                idempotency_key="pg-different-key-1",
            ),
        )
        with pytest.raises(ToolConflictError):
            service.request_tool(
                principal,
                ToolCallRequest(
                    name="phase8.reversible.set",
                    version=1,
                    arguments={"value": 2},
                    idempotency_key="pg-different-key-1",
                ),
            )
    finally:
        service.session.close()


def test_postgresql_approval_decide_and_atomic_consume_races(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    with factory() as session:
        created = ToolPlatformService(session).request_tool(
            principal,
            ToolCallRequest(
                name="phase8.consequential.echo",
                version=1,
                arguments={"message": "race"},
                idempotency_key="pg-approval-race-1",
            ),
        )
    assert created.approval_id is not None
    decision_barrier = Barrier(2)

    def decide(approve: bool) -> str:
        with factory() as session:
            decision_barrier.wait(timeout=5)
            try:
                ToolPlatformService(session).decide_approval(
                    principal, created.approval_id, approve=approve
                )
            except ApprovalError:
                return "rejected_by_lock"
            return "decided"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(decide, (True, False)))
    assert outcomes.count("decided") == 1

    execution_barrier = Barrier(2)

    def execute(_: int) -> str:
        with factory() as session:
            execution_barrier.wait(timeout=5)
            try:
                observation = ToolPlatformService(session).execute_tool_call(principal, created.id)
            except ApprovalError:
                return "rejected_by_consume"
            return observation.status.value

    with factory() as session:
        call = session.get(ToolCall, created.id)
        if call is not None and call.status == ToolCallStatus.REJECTED.value:
            session.rollback()
            created = ToolPlatformService(session).request_tool(
                principal,
                ToolCallRequest(
                    name="phase8.consequential.echo",
                    version=1,
                    arguments={"message": "approved-after-reject"},
                    idempotency_key="pg-approval-recovery-1",
                ),
            )
            assert created.approval_id is not None
            ToolPlatformService(session).decide_approval(
                principal, created.approval_id, approve=True
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        execution_outcomes = list(executor.map(execute, range(2)))
    assert execution_outcomes.count("succeeded") == 1
    assert "rejected_by_consume" in execution_outcomes


def test_postgresql_approval_cancel_race_has_one_terminal_authority(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    with factory() as session:
        created = ToolPlatformService(session).request_tool(
            principal,
            ToolCallRequest(
                name="phase8.critical.echo",
                version=1,
                arguments={"message": "cancel", "confirmation": "owner-confirmed"},
                idempotency_key="pg-cancel-race-1",
            ),
        )
    assert created.approval_id is not None
    barrier = Barrier(2)

    def approve_or_cancel(approve: bool) -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                if approve:
                    ToolPlatformService(session).decide_approval(
                        principal, created.approval_id, approve=True
                    )
                else:
                    ToolPlatformService(session).cancel_tool_call(principal, created.id)
            except (ApprovalError, ToolConflictError):
                return "lost"
            return "won"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(approve_or_cancel, (True, False)))
    assert outcomes.count("won") >= 1
    with factory() as session:
        call = session.get(ToolCall, created.id)
        approval = session.get(Approval, created.approval_id)
        assert call is not None and call.status in {
            ToolCallStatus.APPROVED.value,
            ToolCallStatus.CANCELLED.value,
        }
        assert approval is not None and approval.status in {
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.CANCELLED.value,
        }


def test_postgresql_budget_row_lock_allows_only_bounded_requests(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    barrier = Barrier(5)

    def submit(index: int) -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                response = ToolPlatformService(session).request_tool(
                    principal,
                    ToolCallRequest(
                        name="phase8.status.read",
                        version=1,
                        arguments={"resource": "platform"},
                        idempotency_key=f"phase8-pg-budget-{index:02d}",
                    ),
                )
            except ToolBudgetError:
                return "budget"
            return response.status.value

    with ThreadPoolExecutor(max_workers=5) as executor:
        outcomes = list(executor.map(submit, range(5)))
    assert outcomes.count("approved") == 4
    assert outcomes.count("budget") == 1


def test_postgresql_approve_vs_expire_race(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    fixed_time = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    with factory() as session:
        created = ToolPlatformService(session, clock=lambda: fixed_time).request_tool(
            principal,
            ToolCallRequest(
                name="phase8.consequential.echo",
                version=1,
                arguments={"message": "expire-race"},
                idempotency_key="pg-approve-expire-race-1",
            ),
        )
    assert created.approval_id is not None

    barrier = Barrier(2)
    later_time = fixed_time + timedelta(minutes=15)

    def thread_action(is_approver: bool) -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            service = ToolPlatformService(session, clock=lambda: later_time)
            if is_approver:
                try:
                    service.decide_approval(principal, created.approval_id, approve=True)
                    return "approved"
                except ApprovalError:
                    return "expired_during_decide"
            else:
                count = service.expire_pending()
                return f"expired_count_{count}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(thread_action, (True, False)))

    assert len(outcomes) == 2
    with factory() as session:
        call = session.get(ToolCall, created.id)
        approval = session.get(Approval, created.approval_id)
        assert call is not None and call.status in {
            ToolCallStatus.APPROVED.value,
            ToolCallStatus.EXPIRED.value,
        }
        assert approval is not None and approval.status in {
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.EXPIRED.value,
        }


def test_postgresql_consume_vs_expire_race(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    fixed_time = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    with factory() as session:
        service = ToolPlatformService(session, clock=lambda: fixed_time)
        created = service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.consequential.echo",
                version=1,
                arguments={"message": "consume-expire-race"},
                idempotency_key="pg-consume-expire-race-1",
            ),
        )
        assert created.approval_id is not None
        service.decide_approval(principal, created.approval_id, approve=True)

    barrier = Barrier(2)
    later_time = fixed_time + timedelta(minutes=15)

    def thread_action(is_consumer: bool) -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            service = ToolPlatformService(session, clock=lambda: later_time)
            if is_consumer:
                try:
                    obs = service.execute_tool_call(principal, created.id)
                    return obs.status.value
                except ApprovalError:
                    return "expired_during_consume"
            else:
                count = service.expire_pending()
                return f"expired_count_{count}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(thread_action, (True, False)))

    assert len(outcomes) == 2
    with factory() as session:
        call = session.get(ToolCall, created.id)
        approval = session.get(Approval, created.approval_id)
        assert call is not None and call.status in {
            ToolCallStatus.SUCCEEDED.value,
            ToolCallStatus.EXPIRED.value,
        }
        assert approval is not None and approval.status in {
            ApprovalStatus.CONSUMED.value,
            ApprovalStatus.EXPIRED.value,
        }


def test_postgresql_cancel_vs_expire_race(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    fixed_time = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    with factory() as session:
        created = ToolPlatformService(session, clock=lambda: fixed_time).request_tool(
            principal,
            ToolCallRequest(
                name="phase8.consequential.echo",
                version=1,
                arguments={"message": "cancel-expire-race"},
                idempotency_key="pg-cancel-expire-race-1",
            ),
        )
    assert created.approval_id is not None

    barrier = Barrier(2)
    later_time = fixed_time + timedelta(minutes=15)

    def thread_action(is_canceller: bool) -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            service = ToolPlatformService(session, clock=lambda: later_time)
            if is_canceller:
                try:
                    resp = service.cancel_tool_call(principal, created.id)
                    return resp.status.value
                except (ApprovalError, ToolConflictError):
                    return "expired_during_cancel"
            else:
                count = service.expire_pending()
                return f"expired_count_{count}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(thread_action, (True, False)))

    assert len(outcomes) == 2
    with factory() as session:
        call = session.get(ToolCall, created.id)
        approval = session.get(Approval, created.approval_id)
        assert call is not None and call.status in {
            ToolCallStatus.CANCELLED.value,
            ToolCallStatus.EXPIRED.value,
        }
        assert approval is not None and approval.status in {
            ApprovalStatus.CANCELLED.value,
            ApprovalStatus.EXPIRED.value,
        }


def test_postgresql_cross_owner_and_unauthorized_run_binding_rejection(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    conv_id: UUID
    run_id: UUID
    with factory() as session:
        conv_service = ConversationService(session)
        conv = conv_service.create_conversation(principal, "Postgres binding thread")
        sess = conv_service.create_session(principal, conv.id)
        sub = conv_service.submit_message(
            principal, sess.id, uuid4(), "postgres trigger", correlation_id="pg-bind-1"
        )
        conv_id = conv.id
        run_id = sub.run.id

    foreign_principal = DevicePrincipal(
        owner_id=uuid4(),
        device_id=uuid4(),
        credential_id=uuid4(),
        scopes=frozenset(PHASE_8_SCOPES),
    )

    with factory() as session:
        service = ToolPlatformService(session)
        with pytest.raises(ToolPlatformError):
            service.request_tool(
                foreign_principal,
                ToolCallRequest(
                    name="phase8.status.read",
                    version=1,
                    arguments={"resource": "platform"},
                    idempotency_key="pg-foreign-run-1",
                    run_id=run_id,
                ),
            )
        with pytest.raises(ToolPlatformError):
            service.request_tool(
                foreign_principal,
                ToolCallRequest(
                    name="phase8.status.read",
                    version=1,
                    arguments={"resource": "platform"},
                    idempotency_key="pg-foreign-conv-1",
                    conversation_id=conv_id,
                ),
            )


def test_postgresql_durable_expiry_and_executor_uncertain_outcome(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    fixed_time = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)
    with factory() as session:
        service = ToolPlatformService(session, clock=lambda: fixed_time)
        resp = service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.consequential.echo",
                version=1,
                arguments={"message": "pg-durable-expiry"},
                idempotency_key="pg-durable-exp-1",
            ),
        )
        assert resp.approval_id is not None

    later_time = fixed_time + timedelta(minutes=15)
    with factory() as session:
        service_expired = ToolPlatformService(session, clock=lambda: later_time)
        with pytest.raises(ApprovalError) as exc_info:
            service_expired.decide_approval(principal, resp.approval_id, approve=True)
        assert exc_info.value.code == "approval_expired"

    with factory() as session:
        call = session.get(ToolCall, resp.id)
        approval = session.get(Approval, resp.approval_id)
        assert call is not None and call.status == ToolCallStatus.EXPIRED.value
        assert approval is not None and approval.status == ApprovalStatus.EXPIRED.value

    # Executor uncertain outcome
    with factory() as session:
        service = ToolPlatformService(session)
        resp_crash = service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.uncertain.outcome",
                version=1,
                arguments={},
                idempotency_key="pg-uncertain-crash-1",
            ),
        )
        with pytest.raises(ToolPlatformError) as exc_info2:
            service.execute_tool_call(principal, resp_crash.id)
        assert exc_info2.value.code == "executor_uncertain_outcome"

    with factory() as session:
        call_crash = session.get(ToolCall, resp_crash.id)
        assert call_crash is not None
        assert call_crash.status == ToolCallStatus.FAILED.value
        assert call_crash.failure_code == "executor_uncertain_outcome"


def test_postgresql_run_conversation_mismatch_rejection(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    with factory() as session:
        conv_service = ConversationService(session)
        conv_a = conv_service.create_conversation(principal, "Conversation A")
        conv_b = conv_service.create_conversation(principal, "Conversation B")
        sess_b = conv_service.create_session(principal, conv_b.id)
        sub_b = conv_service.submit_message(
            principal, sess_b.id, uuid4(), "trigger run in conv b", correlation_id="pg-mismatch-1"
        )
        run_b_id = sub_b.run.id

    with factory() as session:
        service = ToolPlatformService(session)
        with pytest.raises(ToolConflictError) as exc_info:
            service.request_tool(
                principal,
                ToolCallRequest(
                    name="phase8.status.read",
                    version=1,
                    arguments={"resource": "platform"},
                    idempotency_key="pg-mismatch-req-1",
                    conversation_id=conv_a.id,
                    run_id=run_b_id,
                ),
            )
        assert exc_info.value.code == "conversation_run_mismatch"


def test_postgresql_parent_run_cancellation_vs_execution_race(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    with factory() as session:
        conv_service = ConversationService(session)
        conv = conv_service.create_conversation(principal, "Parent cancel race")
        sess = conv_service.create_session(principal, conv.id)
        sub = conv_service.submit_message(
            principal, sess.id, uuid4(), "parent trigger", correlation_id="pg-cancel-race-test"
        )
        run_id = sub.run.id
        service = ToolPlatformService(session)
        created = service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="pg-cancel-exec-race-1",
                conversation_id=conv.id,
                run_id=run_id,
            ),
        )
    assert created.status is ToolCallStatus.APPROVED

    barrier = Barrier(2)

    def cancel_or_execute(is_canceller: bool) -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            if is_canceller:
                conv_s = ConversationService(session)
                conv_s.cancel_run(principal, run_id)
                return "cancelled"
            else:
                svc = ToolPlatformService(session)
                try:
                    obs = svc.execute_tool_call(principal, created.id)
                    return obs.status.value
                except ToolDeniedError as exc:
                    return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(cancel_or_execute, (True, False)))

    assert "cancelled" in outcomes
    with factory() as session:
        call = session.get(ToolCall, created.id)
        assert call is not None
        # Must be either SUCCEEDED (executed before cancel) or CANCELLED
        assert call.status in {ToolCallStatus.SUCCEEDED.value, ToolCallStatus.CANCELLED.value}


def test_postgresql_consequential_misconfigured_approval_policy_cannot_execute(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    from pydantic import BaseModel

    class DummyArgs(BaseModel):
        pass

    class DummyOut(BaseModel):
        pass

    # Descriptor construction rejects consequential + NONE
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


def test_postgresql_stricter_descriptor_policy_after_staging_cannot_execute(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    with factory() as session:
        service = ToolPlatformService(session)
        resp = service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="pg-stricter-policy-1",
            ),
        )
        assert resp.status is ToolCallStatus.APPROVED

        stricter_desc = _descriptor(
            "phase8.status.read",
            "Read a synthetic status requiring owner approval.",
            StatusArguments,
            StatusOutput,
            RiskLevel.READ,
            approval=ApprovalPolicy.EXACT_OWNER,
        )
        service.registry = ToolRegistry((stricter_desc,))
        with pytest.raises(ApprovalError) as exc_info:
            service.execute_tool_call(principal, resp.id)
        assert exc_info.value.code == "approval_required_by_current_policy"


def test_postgresql_uncertain_executor_raw_error_not_persisted(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database

    class LeakyCrashExecutor(SyntheticToolExecutor):
        def execute(self, request: Any) -> Any:
            raise RuntimeError(
                "crash with password=supersecret token=bearer_12345 "
                "Authorization=Bearer_abc private_key=pk_xyz"
            )

    with factory() as session:
        service = ToolPlatformService(session, executor=LeakyCrashExecutor())
        resp = service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="pg-leaky-crash-1",
            ),
        )
        assert resp.status is ToolCallStatus.APPROVED

        with pytest.raises(ToolPlatformError) as exc_info:
            service.execute_tool_call(principal, resp.id)
        assert exc_info.value.code == "executor_uncertain_outcome"

        # Verify DB rows
        obs = session.scalar(
            select(ToolObservationRow).where(ToolObservationRow.tool_call_id == resp.id)
        )
        assert obs is not None
        assert "supersecret" not in json.dumps(obs.output_json)
        assert "supersecret" not in json.dumps(obs.verification_json)
        assert obs.output_json.get("error") == "executor_uncertain_outcome"

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.tool_call_id == resp.id,
                AuditEvent.event_type == "tool.failed",
            )
        )
        assert audit is not None
        assert "supersecret" not in json.dumps(audit.metadata_json)
        assert audit.reason_code == "executor_uncertain_outcome"


def test_postgresql_stale_executing_reconciliation_produces_uncertain_outcome_without_retry(
    database: tuple[object, sessionmaker, DevicePrincipal],
) -> None:
    _, factory, principal = database
    call_id = uuid4()
    now = datetime.now(UTC)

    with factory() as session:
        session.add(
            ToolCall(
                id=call_id,
                owner_id=principal.owner_id,
                device_id=principal.device_id,
                tool_name="phase8.consequential.echo",
                tool_version=1,
                arguments_json={"message": "stale action"},
                argument_digest="digest123",
                idempotency_key="pg-stale-exec-0001",
                risk_level=RiskLevel.CONSEQUENTIAL.value,
                policy_version="phase8-v1",
                status=ToolCallStatus.EXECUTING.value,
                started_at=now,
                created_at=now,
            )
        )
        session.commit()

    with factory() as session:
        service = ToolPlatformService(session)
        reconciled = service.reconcile_stale_executing()
        assert reconciled == 1

        call = session.get(ToolCall, call_id)
        assert call is not None
        assert call.status == ToolCallStatus.FAILED.value
        assert call.failure_code == "executor_uncertain_outcome"

        obs = session.scalar(
            select(ToolObservationRow).where(ToolObservationRow.tool_call_id == call_id)
        )
        assert obs is not None
        assert obs.status == ToolObservationStatus.FAILED.value
        assert obs.failure_code == "executor_uncertain_outcome"
        assert obs.verification_json.get("uncertain_outcome") is True
        assert obs.verification_json.get("reconciled_after_stale") is True

        replay_obs = service.execute_tool_call(principal, call_id)
        assert replay_obs.status is ToolObservationStatus.FAILED
        assert replay_obs.failure_code == "executor_uncertain_outcome"
