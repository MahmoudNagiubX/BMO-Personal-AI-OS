from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from personal_ai_os.identity.contracts import PHASE_8_SCOPES, EnrollmentGrant
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.tools.contracts import ApprovalStatus, ToolCallRequest, ToolCallStatus
from personal_ai_os.tools.errors import ApprovalError, ToolBudgetError, ToolConflictError
from personal_ai_os.tools.models import Approval, ToolCall
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


def _provision(factory: sessionmaker) -> tuple[UUID, object]:
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
def database(test_database_url: str) -> tuple[object, sessionmaker, object]:
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
    database: tuple[object, sessionmaker, object],
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
    database: tuple[object, sessionmaker, object],
) -> None:
    _, factory, principal = database
    service = ToolPlatformService(factory())
    try:
        service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key="pg-different-key-1",
            ),
        )
        with pytest.raises(ToolConflictError):
            service.request_tool(
                principal,
                ToolCallRequest(
                    name="phase8.status.read",
                    version=1,
                    arguments={"resource": "other"},
                    idempotency_key="pg-different-key-1",
                ),
            )
    finally:
        service.session.close()


def test_postgresql_approval_decide_and_atomic_consume_races(
    database: tuple[object, sessionmaker, object],
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
    database: tuple[object, sessionmaker, object],
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
    database: tuple[object, sessionmaker, object],
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
                        idempotency_key=f"pg-budget-{index:02d}",
                    ),
                )
            except ToolBudgetError:
                return "budget"
            return response.status.value

    with ThreadPoolExecutor(max_workers=5) as executor:
        outcomes = list(executor.map(submit, range(5)))
    assert outcomes.count("approved") == 4
    assert outcomes.count("budget") == 1
