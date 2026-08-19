from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_os.app import create_app
from personal_ai_os.conversations.errors import (
    ConversationBusyError,
    ConversationSessionNotFoundError,
)
from personal_ai_os.conversations.models import (
    AgentRun,
    ConversationMessage,
    ConversationSession,
    RunEvent,
)
from personal_ai_os.conversations.reconciliation import ConversationReconciliationGate
from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.core.config import get_settings
from personal_ai_os.identity.contracts import (
    PHASE_6_SCOPES,
    PHASE_7_SCOPES,
    DevicePrincipal,
    EnrollmentGrant,
)
from personal_ai_os.identity.errors import (
    AuthenticationError,
    EnrollmentRejectedError,
    OwnerBootstrapError,
)
from personal_ai_os.identity.models import Device, DeviceCredential, Owner
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.model_gateway import ModelGateway
from tests.unit.model_gateway.fakes import FakeProvider

pytestmark = pytest.mark.integration
EXPECTED_REVISION = "20260819_0003"


def _all_phase7_scopes() -> list[str]:
    return sorted(PHASE_6_SCOPES | PHASE_7_SCOPES)


def _provision_conversation(
    factory: sessionmaker,
) -> tuple[UUID, UUID, DevicePrincipal]:
    with factory() as session:
        identity = IdentityService(session)
        owner = identity.bootstrap_owner("Synthetic Phase 7 owner")
        enrollment = identity.create_enrollment(
            EnrollmentGrant(
                owner_id=owner.id,
                display_name="Synthetic Phase 7 client",
                device_kind="windows_client",
                platform="windows",
                scopes=_all_phase7_scopes(),
            )
        )
        credential = identity.redeem_enrollment(enrollment.code)
        principal = identity.authenticate(credential.raw)
        service = ConversationService(session)
        conversation = service.create_conversation(principal, "Synthetic race thread")
        conversation_session = service.create_session(principal, conversation.id)
        return conversation.id, conversation_session.id, principal


@pytest.fixture
def test_database_url() -> str:
    value = os.environ.get("BMO_TEST_DATABASE_URL")
    if not value:
        pytest.skip("BMO_TEST_DATABASE_URL is not set")
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+psycopg":
        pytest.fail("BMO_TEST_DATABASE_URL must use postgresql+psycopg")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("integration tests only accept a localhost PostgreSQL URL")
    if not parsed.path or parsed.path == "/":
        pytest.fail("BMO_TEST_DATABASE_URL must include a database name")
    return value


def test_postgresql_connection_and_vector_extension(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            extension = connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
            assert extension == "vector"
    finally:
        engine.dispose()


def test_alembic_head_is_applied(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == EXPECTED_REVISION
    finally:
        engine.dispose()


def test_readiness_uses_real_database(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BMO_ENVIRONMENT", "test")
    monkeypatch.setenv("BMO_DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
    finally:
        get_settings.cache_clear()


def test_concurrent_enrollment_redemption_has_exactly_one_success(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        with factory() as session:
            service = IdentityService(session)
            owner = service.bootstrap_owner("Synthetic concurrent owner")
            enrollment = service.create_enrollment(
                EnrollmentGrant(
                    owner_id=owner.id,
                    display_name="Synthetic concurrent client",
                    device_kind="windows_client",
                    platform="windows",
                    scopes=["device.self.read"],
                    capabilities=["system.health"],
                )
            )

        barrier = Barrier(2)

        def redeem_once() -> bool:
            with factory() as session:
                barrier.wait(timeout=5)
                try:
                    IdentityService(session).redeem_enrollment(enrollment.code)
                except EnrollmentRejectedError:
                    return False
                return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: redeem_once(), range(2)))

        with factory() as session:
            device_count = session.scalar(
                select(func.count()).select_from(Device).where(Device.owner_id == owner.id)
            )
            credential_count = session.scalar(
                select(func.count())
                .select_from(DeviceCredential)
                .join(Device, Device.id == DeviceCredential.device_id)
                .where(Device.owner_id == owner.id, DeviceCredential.revoked_at.is_(None))
            )
        assert sorted(results) == [False, True]
        assert device_count == 1
        assert credential_count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_concurrent_owner_bootstrap_has_exactly_one_success(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))

        def bootstrap_once() -> bool:
            with factory() as session:
                barrier.wait(timeout=5)
                try:
                    IdentityService(session).bootstrap_owner("Synthetic concurrent owner")
                except OwnerBootstrapError:
                    return False
                return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: bootstrap_once(), range(2)))

        with factory() as session:
            owner_count = session.scalar(select(func.count()).select_from(Owner))
        assert sorted(results) == [False, True]
        assert owner_count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_concurrent_rotation_and_revocation_finish_fail_closed(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        with factory() as session:
            service = IdentityService(session)
            owner = service.bootstrap_owner("Synthetic race owner")
            enrollment = service.create_enrollment(
                EnrollmentGrant(
                    owner_id=owner.id,
                    display_name="Synthetic race client",
                    device_kind="windows_client",
                    platform="windows",
                    scopes=["device.credential.rotate"],
                )
            )
            credential = service.redeem_enrollment(enrollment.code)
            principal = service.authenticate(credential.raw)

        def rotate_once() -> str:
            with factory() as session:
                barrier.wait(timeout=5)
                try:
                    IdentityService(session).rotate_credential(principal)
                except AuthenticationError:
                    return "rotation_rejected"
                return "rotation_completed"

        def revoke_once() -> str:
            with factory() as session:
                barrier.wait(timeout=5)
                IdentityService(session).revoke_device(credential.device_id)
                return "revocation_completed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(rotate_once), executor.submit(revoke_once)]
            outcomes = [future.result(timeout=10) for future in results]

        with factory() as session:
            device = session.get(Device, credential.device_id)
            live_credentials = session.scalar(
                select(func.count())
                .select_from(DeviceCredential)
                .where(
                    DeviceCredential.device_id == credential.device_id,
                    DeviceCredential.revoked_at.is_(None),
                )
            )
        assert "revocation_completed" in outcomes
        assert device is not None
        assert device.status == "revoked"
        assert live_credentials == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_postgresql_same_idempotency_key_has_one_insert_and_one_replay(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)
    conversation_id: UUID | None = None
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        conversation_id, session_id, principal = _provision_conversation(factory)
        client_message_id = uuid4()

        def submit_once() -> bool:
            with factory() as session:
                barrier.wait(timeout=5)
                result = ConversationService(session).submit_message(
                    principal,
                    session_id,
                    client_message_id,
                    "same synthetic content",
                    correlation_id="phase7-postgres-idempotency",
                )
                return result.replayed

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit_once(), range(2)))

        with factory() as session:
            message_count = session.execute(
                text(
                    "SELECT count(*) FROM conversation_messages "
                    "WHERE conversation_id = :conversation_id"
                ),
                {"conversation_id": conversation_id},
            ).scalar_one()
        assert sorted(results) == [False, True]
        assert message_count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_postgresql_two_sessions_serialize_active_runs(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        conversation_id, first_session_id, principal = _provision_conversation(factory)
        with factory() as session:
            second_session_id = (
                ConversationService(session).create_session(principal, conversation_id).id
            )

        def submit_from(session_id: UUID) -> str:
            with factory() as session:
                barrier.wait(timeout=5)
                try:
                    ConversationService(session).submit_message(
                        principal,
                        session_id,
                        uuid4(),
                        "one active synthetic run",
                        correlation_id="phase7-postgres-active-run",
                    )
                except ConversationBusyError:
                    return "busy"
                return "accepted"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(submit_from, (first_session_id, second_session_id)))
        assert sorted(outcomes) == ["accepted", "busy"]
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_postgresql_cancel_finalization_race_has_no_assistant_after_cancel(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    entered = Event()
    release = Event()
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        conversation_id, session_id, principal = _provision_conversation(factory)
        with factory() as session:
            submission = ConversationService(session).submit_message(
                principal,
                session_id,
                uuid4(),
                "cancel race synthetic request",
                correlation_id="phase7-postgres-cancel-race",
            )
        provider = FakeProvider()
        provider.entered = entered
        provider.release = release

        def execute() -> None:
            with factory() as session:
                ConversationService(session).execute_run(submission.run.id, ModelGateway(provider))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(execute)
            assert entered.wait(timeout=10)
            with factory() as session:
                cancelled = ConversationService(session).cancel_run(principal, submission.run.id)
                assert cancelled.status == "cancel_requested"
            release.set()
            future.result(timeout=10)

        with factory() as session:
            service = ConversationService(session)
            run = service.get_run(principal, submission.run.id)
            messages = service.get_messages(principal, conversation_id, limit=10)
        assert run.status == "cancelled"
        assert [message.role for message in messages] == ["user"]
    finally:
        release.set()
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_postgresql_close_session_and_finalization_serialize_event_sequence(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    entered = Event()
    release = Event()
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        conversation_id, session_id, principal = _provision_conversation(factory)
        with factory() as session:
            submission = ConversationService(session).submit_message(
                principal,
                session_id,
                uuid4(),
                "close and finalize synthetic race",
                correlation_id="phase7-postgres-close-finalize",
            )
        provider = FakeProvider()
        provider.entered = entered
        provider.release = release

        def execute() -> None:
            with factory() as session:
                ConversationService(session).execute_run(submission.run.id, ModelGateway(provider))

        def close() -> None:
            with factory() as session:
                ConversationService(session).close_session(principal, session_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            execution = executor.submit(execute)
            assert entered.wait(timeout=10)
            closing = executor.submit(close)
            release.set()
            execution.result(timeout=10)
            closing.result(timeout=10)

        with factory() as session:
            run = session.get(AgentRun, submission.run.id)
            closed_session = session.get(ConversationSession, session_id)
            events = list(
                session.scalars(
                    select(RunEvent)
                    .where(RunEvent.session_id == session_id)
                    .order_by(RunEvent.sequence)
                )
            )
            messages = list(
                session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.ordinal)
                )
            )
        assert run is not None
        assert closed_session is not None
        assert closed_session.status == "closed"
        assert run.status in {"succeeded", "cancelled"}
        assert run.status != "queued"
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assistant_messages = [message for message in messages if message.role == "assistant"]
        assert bool(assistant_messages) is (run.status == "succeeded")
    finally:
        release.set()
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


@pytest.mark.parametrize("stale_status", ["queued", "running", "cancel_requested"])
def test_postgresql_deferred_reconciliation_recovers_stale_run(
    test_database_url: str,
    stale_status: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        conversation_id, session_id, principal = _provision_conversation(factory)
        with factory() as session:
            submission = ConversationService(session).submit_message(
                principal,
                session_id,
                uuid4(),
                f"deferred reconciliation {stale_status}",
                correlation_id=f"phase7-postgres-reconciliation-{stale_status}",
            )
            run = session.get(AgentRun, submission.run.id)
            assert run is not None
            run.status = stale_status
            if stale_status == "running":
                run.started_at = run.created_at
            elif stale_status == "cancel_requested":
                run.cancel_requested_at = run.created_at
            session.commit()

        gate = ConversationReconciliationGate()
        factory_calls = 0

        def deferred_then_postgres() -> Session:
            nonlocal factory_calls
            factory_calls += 1
            if factory_calls == 1:
                raise ConnectionError("synthetic startup database outage")
            return factory()

        assert gate.attempt(deferred_then_postgres) is False
        assert gate.deferred is True
        assert gate.ready is False
        assert gate.attempts == 1

        assert gate.ensure_ready(factory) is True
        assert gate.deferred is False
        assert gate.ready is True
        assert gate.attempts == 2

        with factory() as session:
            recovered = session.get(AgentRun, submission.run.id)
            assert recovered is not None
            assert recovered.status == "failed"
            assert recovered.failure_category == "interrupted"
            assert recovered.failure_code == "server_restart_interrupted"
            assert recovered.completed_at is not None
            assert ConversationService(session).repository.active_run(conversation_id) is None

            new_submission = ConversationService(session).submit_message(
                principal,
                session_id,
                uuid4(),
                f"new work after {stale_status} recovery",
                correlation_id=f"phase7-postgres-reconciliation-new-{stale_status}",
            )
            assert new_submission.replayed is False
            assert new_submission.run.status == "queued"
            assert new_submission.run.id != recovered.id

            stale_after_acceptance = session.get(AgentRun, submission.run.id)
            assert stale_after_acceptance is not None
            assert stale_after_acceptance.status == "failed"
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()


def test_postgresql_session_ownership_is_fail_closed(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        _conversation_id, session_id, principal = _provision_conversation(factory)
        with factory() as session:
            identity = IdentityService(session)
            owner = session.get(Owner, principal.owner_id)
            assert owner is not None
            owner_id = owner.id
            session.rollback()
            enrollment = identity.create_enrollment(
                EnrollmentGrant(
                    owner_id=owner_id,
                    display_name="Synthetic second device",
                    device_kind="android_client",
                    platform="android",
                    scopes=_all_phase7_scopes(),
                )
            )
            second_principal = identity.authenticate(
                identity.redeem_enrollment(enrollment.code).raw
            )
        with factory() as session, pytest.raises(ConversationSessionNotFoundError):
            ConversationService(session).get_session(second_principal, session_id)
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()
