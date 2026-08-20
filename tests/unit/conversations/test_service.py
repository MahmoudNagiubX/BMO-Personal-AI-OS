from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_os.conversations.errors import (
    ConversationBusyError,
    IdempotencyConflictError,
)
from personal_ai_os.conversations.executor import ConversationExecutor
from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.identity.contracts import (
    PHASE_6_SCOPES,
    PHASE_7_SCOPES,
    EnrollmentGrant,
)
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.model_gateway import ModelGateway
from personal_ai_os.model_gateway.provider import ProviderOfflineError
from tests.unit.identity.conftest import NOW
from tests.unit.model_gateway.fakes import FakeProvider

ALL_PHASE_7_SCOPES = sorted(PHASE_6_SCOPES | PHASE_7_SCOPES)


def provision_phase7(session: Session):
    identity = IdentityService(session, clock=lambda: NOW)
    owner = identity.bootstrap_owner("Synthetic conversation owner")
    enrollment = identity.create_enrollment(
        EnrollmentGrant(
            owner_id=owner.id,
            display_name="Synthetic text client",
            device_kind="windows_client",
            platform="windows",
            scopes=ALL_PHASE_7_SCOPES,
            capabilities=[],
        )
    )
    credential = identity.redeem_enrollment(enrollment.code)
    principal = identity.authenticate(credential.raw)
    return principal


def test_successful_run_uses_chat_gateway_and_links_assistant(
    session: Session,
) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, "Synthetic thread")
    conversation_session = service.create_session(principal, conversation.id)
    submission = service.submit_message(
        principal,
        conversation_session.id,
        uuid4(),
        "Hello from a synthetic test.",
        correlation_id="phase7-test",
    )
    provider = FakeProvider()
    service.execute_run(submission.run.id, ModelGateway(provider))

    runs = service.get_runs(principal, conversation.id, limit=10)
    messages = service.get_messages(principal, conversation.id, limit=10)
    assert runs[0].status == "succeeded"
    assert len(messages) == 2
    assert messages[1].role == "assistant"
    assert messages[1].run_id == runs[0].id
    assert provider.last_generation is not None
    assert provider.last_generation.tools == ()
    assert provider.last_generation.messages[0].role.value == "system"

    events = service.replay_events(principal, conversation_session.id, 0)
    assert [event.event_type for event in events][-2:] == [
        "run.succeeded",
        "assistant.message.ready",
    ]
    assert events == sorted(events, key=lambda event: event.sequence)


def test_idempotency_replay_and_different_content_conflict(session: Session) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    client_message_id = uuid4()
    first = service.submit_message(
        principal,
        conversation_session.id,
        client_message_id,
        "same content",
        correlation_id=None,
    )
    replay = service.submit_message(
        principal,
        conversation_session.id,
        client_message_id,
        "same content",
        correlation_id=None,
    )
    assert first.run.id == replay.run.id
    assert replay.replayed is True
    with pytest.raises(IdempotencyConflictError):
        service.submit_message(
            principal,
            conversation_session.id,
            client_message_id,
            "different content",
            correlation_id=None,
        )


def test_idempotency_same_content_with_different_model_conflicts(session: Session) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    client_message_id = uuid4()
    service.submit_message(
        principal,
        conversation_session.id,
        client_message_id,
        "same content",
        correlation_id=None,
        requested_model="fast",
    )

    with pytest.raises(IdempotencyConflictError):
        service.submit_message(
            principal,
            conversation_session.id,
            client_message_id,
            "same content",
            correlation_id=None,
            requested_model="advanced",
        )


def test_one_active_run_per_conversation_is_enforced(session: Session) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    service.submit_message(
        principal, conversation_session.id, uuid4(), "first", correlation_id=None
    )
    with pytest.raises(ConversationBusyError):
        service.submit_message(
            principal, conversation_session.id, uuid4(), "second", correlation_id=None
        )


def test_failed_gateway_run_has_no_assistant_message(session: Session) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    submission = service.submit_message(
        principal, conversation_session.id, uuid4(), "offline request", correlation_id=None
    )
    provider = FakeProvider()
    provider.generation_failures = [
        ProviderOfflineError("offline"),
        ProviderOfflineError("offline"),
    ]
    service.execute_run(submission.run.id, ModelGateway(provider, sleeper=lambda _: None))
    run = service.get_run(principal, submission.run.id)
    messages = service.get_messages(principal, conversation.id, limit=10)
    assert run.status == "failed"
    assert run.failure_category == "provider_unavailable"
    assert [message.role for message in messages] == ["user"]


def test_queued_cancellation_is_terminal_and_skips_gateway(session: Session) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    submission = service.submit_message(
        principal, conversation_session.id, uuid4(), "cancel me", correlation_id=None
    )
    cancelled = service.cancel_run(principal, submission.run.id)
    provider = FakeProvider()
    service.execute_run(submission.run.id, ModelGateway(provider))
    assert cancelled.status == "cancelled"
    assert provider.generation_calls == 0
    assert service.get_run(principal, submission.run.id).status == "cancelled"


def test_restart_reconciliation_fails_orphaned_run(session: Session) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    submission = service.submit_message(
        principal, conversation_session.id, uuid4(), "interrupted", correlation_id=None
    )
    assert service.reconcile_interrupted_runs() == 1
    run = service.get_run(principal, submission.run.id)
    assert run.status == "failed"
    assert run.failure_code == "server_restart_interrupted"


def test_executor_exception_persists_redacted_failure_and_no_assistant(
    session: Session,
) -> None:
    principal = provision_phase7(session)
    service = ConversationService(session)
    conversation = service.create_conversation(principal, None)
    conversation_session = service.create_session(principal, conversation.id)
    submission = service.submit_message(
        principal, conversation_session.id, uuid4(), "executor failure", correlation_id=None
    )
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)

    def raise_executor_error() -> ModelGateway:
        raise RuntimeError("synthetic provider secret")

    session.commit()
    session.close()
    executor = ConversationExecutor(factory, raise_executor_error)
    executor.submit(submission.run.id)
    executor.shutdown()

    with factory() as check_session:
        check_service = ConversationService(check_session)
        run = check_service.get_run(principal, submission.run.id)
        messages = check_service.get_messages(principal, conversation.id, limit=10)
    assert run.status == "failed"
    assert run.failure_category == "internal"
    assert run.failure_code == "executor_failed"
    assert [message.role for message in messages] == ["user"]
