"""Transactional Phase 7 conversation lifecycle and ModelGateway boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from personal_ai_os.conversations.contracts import (
    ConversationResponse,
    ConversationSessionResponse,
    EventEnvelope,
    MessageResponse,
    RunResponse,
)
from personal_ai_os.conversations.errors import (
    AgentRunNotFoundError,
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationSessionNotFoundError,
    IdempotencyConflictError,
    SessionClosedError,
)
from personal_ai_os.conversations.models import (
    AgentRun,
    Conversation,
    ConversationMessage,
    ConversationSession,
    RunEvent,
    utc_now,
)
from personal_ai_os.conversations.repository import ConversationRepository
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.model_gateway import (
    Capability,
    GenerationRequest,
    GenerationResponse,
    Message,
    MessageRole,
    Modality,
    ModelGateway,
    route_model,
)
from personal_ai_os.model_gateway.errors import ModelGatewayError

MAX_HISTORY_MESSAGES = 16
MAX_HISTORY_TEXT_CHARS = 6000
MAX_EVENT_REPLAY = 100
SYSTEM_INSTRUCTION = (
    "You are BMO in a text-only conversation. No tools are available. "
    "Do not claim that an external action was executed."
)


@dataclass(frozen=True, slots=True)
class Submission:
    """Internal submission result used by the HTTP layer and executor."""

    message: ConversationMessage
    run: AgentRun
    replayed: bool


class ConversationService:
    """Own conversation authorization, persistence, and truthful run transitions."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ConversationRepository(session)

    def create_conversation(self, principal: DevicePrincipal, title: str | None) -> Conversation:
        """Create an active owner-scoped thread attributed to the requesting device."""

        with self.session.begin():
            conversation = Conversation(
                owner_id=principal.owner_id,
                created_by_device_id=principal.device_id,
                title=title,
                status="active",
            )
            self.repository.add(conversation)
            self.repository.flush()
        return conversation

    def list_conversations(
        self, principal: DevicePrincipal, *, limit: int, offset: int
    ) -> list[Conversation]:
        """List only conversations owned by the authenticated owner."""

        with self.session.begin():
            return self.repository.conversations(principal.owner_id, limit=limit, offset=offset)

    def get_conversation(self, principal: DevicePrincipal, conversation_id: UUID) -> Conversation:
        """Read one owner-scoped conversation without cross-owner existence leaks."""

        with self.session.begin():
            conversation = self.repository.conversation(principal.owner_id, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError("conversation is not available")
            return conversation

    def create_session(
        self, principal: DevicePrincipal, conversation_id: UUID
    ) -> ConversationSession:
        """Open a new device-attributed session on an owner conversation."""

        now = utc_now()
        with self.session.begin():
            conversation = self.repository.conversation(principal.owner_id, conversation_id)
            if conversation is None or conversation.status != "active":
                raise ConversationNotFoundError("conversation is not available")
            conversation.updated_at = now
            session = ConversationSession(
                conversation_id=conversation.id,
                owner_id=principal.owner_id,
                device_id=principal.device_id,
                status="active",
                last_seen_at=now,
            )
            self.repository.add(session)
            self.repository.flush()
            self._emit(session, event_type="session.ready", payload={})
        return session

    def get_session(self, principal: DevicePrincipal, session_id: UUID) -> ConversationSession:
        """Read a session only from its owner and creating device."""

        with self.session.begin():
            return self._authorized_session(principal, session_id)

    def close_session(self, principal: DevicePrincipal, session_id: UUID) -> ConversationSession:
        """Close a live session idempotently."""

        now = utc_now()
        with self.session.begin():
            session = self._authorized_session(principal, session_id, lock=True)
            if session.status == "active":
                session.status = "closed"
                session.closed_at = now
                session.last_seen_at = now
                self._emit(session, event_type="session.closed", payload={})
            return session

    def submit_message(
        self,
        principal: DevicePrincipal,
        session_id: UUID,
        client_message_id: UUID,
        content: str,
        *,
        correlation_id: str | None,
        requested_model: str = "fast",
    ) -> Submission:
        """Atomically enforce idempotency, one active run, and lifecycle events."""

        try:
            with self.session.begin():
                session = self._authorized_session(principal, session_id, lock=True)
                if session.status != "active":
                    raise SessionClosedError("conversation session is closed")
                existing = self.repository.message_by_client_id(
                    session.conversation_id, principal.device_id, client_message_id
                )
                if existing is not None:
                    if existing.content != content:
                        raise IdempotencyConflictError("idempotency key has different content")
                    if existing.run_id is None:
                        raise IdempotencyConflictError("idempotent message has no run")
                    existing_run = self.repository.run(existing.run_id)
                    if existing_run is None:
                        raise IdempotencyConflictError("idempotent run is unavailable")
                    if (existing_run.requested_model or "fast") != requested_model:
                        raise IdempotencyConflictError(
                            "idempotency key has different model profile"
                        )
                    return Submission(existing, existing_run, True)
                if self.repository.active_run(session.conversation_id) is not None:
                    raise ConversationBusyError("conversation already has an active run")
                conversation = self.repository.conversation(
                    principal.owner_id, session.conversation_id
                )
                if conversation is None or conversation.status != "active":
                    raise ConversationNotFoundError("conversation is not available")
                message = ConversationMessage(
                    conversation_id=conversation.id,
                    session_id=session.id,
                    author_device_id=principal.device_id,
                    role="user",
                    content=content,
                    ordinal=self.repository.next_message_ordinal(conversation.id),
                    client_message_id=client_message_id,
                )
                self.repository.add(message)
                self.repository.flush()
                run = AgentRun(
                    conversation_id=conversation.id,
                    session_id=session.id,
                    request_device_id=principal.device_id,
                    trigger_message_id=message.id,
                    status="queued",
                    model_request_id=str(uuid4()),
                    requested_model=requested_model,
                    correlation_id=correlation_id,
                )
                self.repository.add(run)
                self.repository.flush()
                message.run_id = run.id
                now = utc_now()
                conversation.last_message_at = now
                conversation.updated_at = now
                session.last_seen_at = now
                self._emit(
                    session,
                    run=run,
                    event_type="message.accepted",
                    payload={"message_id": str(message.id)},
                )
                self._emit(session, run=run, event_type="run.queued", payload={})
                return Submission(message, run, False)
        except IntegrityError as error:
            self.session.rollback()
            session_row = self.repository.session_for_owner(principal.owner_id, session_id)
            if session_row is None:
                raise ConversationSessionNotFoundError(
                    "conversation session is not available"
                ) from error
            existing = self.repository.message_by_client_id(
                session_row.conversation_id, principal.device_id, client_message_id
            )
            if existing is not None:
                if existing.content != content or existing.run_id is None:
                    raise IdempotencyConflictError(
                        "idempotency key has different content"
                    ) from error
                existing_run = self.repository.run(existing.run_id)
                if existing_run is None:
                    raise IdempotencyConflictError("idempotent run is unavailable") from error
                if (existing_run.requested_model or "fast") != requested_model:
                    raise IdempotencyConflictError(
                        "idempotency key has different model profile"
                    ) from error
                return Submission(existing, existing_run, True)
            if self.repository.active_run(session_row.conversation_id) is not None:
                raise ConversationBusyError("conversation already has an active run") from error
            raise

    def get_messages(
        self, principal: DevicePrincipal, conversation_id: UUID, *, limit: int
    ) -> list[ConversationMessage]:
        """Return bounded owner-scoped canonical message content."""

        with self.session.begin():
            if self.repository.conversation(principal.owner_id, conversation_id) is None:
                raise ConversationNotFoundError("conversation is not available")
            return self.repository.messages(principal.owner_id, conversation_id, limit=limit)

    def get_runs(
        self, principal: DevicePrincipal, conversation_id: UUID, *, limit: int
    ) -> list[AgentRun]:
        """Return factual bounded run history for an owner conversation."""

        with self.session.begin():
            if self.repository.conversation(principal.owner_id, conversation_id) is None:
                raise ConversationNotFoundError("conversation is not available")
            return self.repository.runs(principal.owner_id, conversation_id, limit=limit)

    def get_run(self, principal: DevicePrincipal, run_id: UUID) -> AgentRun:
        """Read one run only when its conversation belongs to the owner."""

        with self.session.begin():
            run = self.repository.run(run_id)
            if (
                run is None
                or self.repository.conversation(principal.owner_id, run.conversation_id) is None
            ):
                raise AgentRunNotFoundError("run is not available")
            return run

    def cancel_run(self, principal: DevicePrincipal, run_id: UUID) -> AgentRun:
        """Request cancellation without falsely claiming provider abort."""

        now = utc_now()
        with self.session.begin():
            run = self.repository.run_locked(run_id)
            if (
                run is None
                or self.repository.conversation(principal.owner_id, run.conversation_id) is None
            ):
                raise AgentRunNotFoundError("run is not available")
            if run.request_device_id != principal.device_id:
                raise AgentRunNotFoundError("run is not available")
            session = self._authorized_session(principal, run.session_id, lock=False)
            if run.status == "queued":
                run.status = "cancelled"
                run.completed_at = now
                self._emit(session, run=run, event_type="run.cancelled", payload={})
            elif run.status == "running":
                run.status = "cancel_requested"
                run.cancel_requested_at = now
                self._emit(session, run=run, event_type="run.cancel_requested", payload={})
            return run

    def execute_run(self, run_id: UUID, gateway: ModelGateway) -> None:
        """Execute one queued run outside database locks through ModelGateway only."""

        with self.session.begin():
            run = self.repository.run_locked(run_id)
            if run is None or run.status != "queued":
                return
            run.status = "running"
            run.started_at = utc_now()
            if run.model_request_id is None:
                run.model_request_id = str(uuid4())
            session = self.session.get(ConversationSession, run.session_id)
            if session is None:
                return
            self._emit(session, run=run, event_type="run.started", payload={})
            conversation_id = run.conversation_id
            request_id = run.model_request_id
        with self.session.begin():
            run = self.repository.run(run_id)
            if run is None:
                return
            context, truncated = self._assemble_context(conversation_id, run.trigger_message_id)
        request = GenerationRequest(
            request_id=request_id,
            capability=Capability.CHAT,
            messages=context,
            context_tokens=4096,
            max_output_tokens=256,
            tools=(),
            requested_model=run.requested_model or "fast",
        )
        try:
            response = gateway.generate(request)
        except ModelGatewayError as error:
            self._finalize_failure(run_id, str(error.category.value), error.reason_code)
            return
        except Exception:
            self._finalize_failure(run_id, "internal", "run_execution_failed")
            return
        self._finalize_response(run_id, response, truncated)

    def reconcile_interrupted_runs(self) -> int:
        """Fail non-terminal runs left by a prior Core API process."""

        count = 0
        with self.session.begin():
            for run in self.repository.nonterminal_runs():
                session = self.session.get(ConversationSession, run.session_id)
                if session is None:
                    continue
                run.status = "failed"
                run.failure_category = "interrupted"
                run.failure_code = "server_restart_interrupted"
                run.completed_at = utc_now()
                self._emit(
                    session,
                    run=run,
                    event_type="run.interrupted",
                    payload={"failure_code": "server_restart_interrupted"},
                )
                count += 1
        return count

    def fail_unexpected_run(self, run_id: UUID) -> None:
        """Persist one generic executor failure when the worker boundary catches an error."""

        self._finalize_failure(run_id, "internal", "executor_failed")

    def replay_events(
        self, principal: DevicePrincipal, session_id: UUID, after_sequence: int
    ) -> list[EventEnvelope]:
        """Return only persisted events newer than the supplied non-secret cursor."""

        with self.session.begin():
            session = self._authorized_session(principal, session_id)
            events = self.repository.events_after(
                session.id, after_sequence, limit=MAX_EVENT_REPLAY
            )
            return [self._event_envelope(event) for event in events]

    def _authorized_session(
        self, principal: DevicePrincipal, session_id: UUID, *, lock: bool = False
    ) -> ConversationSession:
        session = (
            self.repository.session_locked(session_id)
            if lock
            else self.repository.session_for_owner(principal.owner_id, session_id)
        )
        if (
            session is None
            or session.owner_id != principal.owner_id
            or session.device_id != principal.device_id
        ):
            raise ConversationSessionNotFoundError("conversation session is not available")
        return session

    def _emit(
        self,
        session: ConversationSession,
        *,
        event_type: str,
        payload: dict[str, Any],
        run: AgentRun | None = None,
    ) -> RunEvent:
        locked_session = self.repository.session_locked(session.id)
        if locked_session is None:
            raise RuntimeError("conversation session is unavailable")
        event = RunEvent(
            conversation_id=locked_session.conversation_id,
            session_id=locked_session.id,
            run_id=None if run is None else run.id,
            sequence=self.repository.next_event_sequence(locked_session.id),
            event_type=event_type,
            payload_json=payload,
        )
        self.repository.add(event)
        self.repository.flush()
        if run is not None:
            if run.event_sequence_start is None:
                run.event_sequence_start = event.sequence
            run.event_sequence_end = event.sequence
        return event

    def _assemble_context(
        self, conversation_id: UUID, current_message_id: UUID
    ) -> tuple[tuple[Message, ...], bool]:
        messages = self.repository.conversation_messages(conversation_id)
        current = next((item for item in messages if item.id == current_message_id), None)
        if current is None or current.role != "user":
            raise ValueError("run trigger message is unavailable")
        prior = [item for item in messages if item.ordinal < current.ordinal]
        selected: list[ConversationMessage] = [current]
        used_chars = len(current.content)
        for item in reversed(prior):
            if len(selected) >= MAX_HISTORY_MESSAGES:
                break
            if used_chars + len(item.content) > MAX_HISTORY_TEXT_CHARS:
                continue
            selected.append(item)
            used_chars += len(item.content)
        selected.sort(key=lambda item: item.ordinal)
        truncated = len(selected) != len(messages)
        result = [Message(MessageRole.SYSTEM, SYSTEM_INSTRUCTION)]
        result.extend(
            Message(
                MessageRole.USER if item.role == "user" else MessageRole.ASSISTANT, item.content
            )
            for item in selected
        )
        return tuple(result), truncated

    def _finalize_response(
        self, run_id: UUID, response: GenerationResponse, context_truncated: bool
    ) -> None:
        with self.session.begin():
            run = self.repository.run_locked(run_id)
            if run is None or run.status in {"succeeded", "failed", "cancelled"}:
                return
            session = self.session.get(ConversationSession, run.session_id)
            conversation = self.session.get(Conversation, run.conversation_id)
            if session is None or conversation is None:
                return
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.completed_at = utc_now()
                self._emit(session, run=run, event_type="run.cancelled", payload={})
                return
            if not self._valid_response(run, response):
                self._mark_failed(run, session, "contract", "invalid_gateway_response")
                return
            assistant = ConversationMessage(
                conversation_id=run.conversation_id,
                session_id=run.session_id,
                run_id=run.id,
                author_device_id=None,
                role="assistant",
                content=response.text,
                ordinal=self.repository.next_message_ordinal(run.conversation_id),
            )
            self.repository.add(assistant)
            self.repository.flush()
            run.status = "succeeded"
            run.completed_at = utc_now()
            run.model_id = response.model.model_id
            run.executed_provider = response.model.provider.value
            run.model_digest = response.model.digest
            run.finish_reason = response.finish_reason[:64]
            run.prompt_usage = response.usage.prompt_tokens
            run.output_usage = response.usage.output_tokens
            run.latency_ms = max(0.0, response.latency_seconds * 1000)
            run.context_truncated = context_truncated
            self._emit(session, run=run, event_type="run.succeeded", payload={})
            self._emit(
                session,
                run=run,
                event_type="assistant.message.ready",
                payload={"assistant_message_id": str(assistant.id)},
            )

    def _finalize_failure(self, run_id: UUID, category: str, code: str) -> None:
        with self.session.begin():
            run = self.repository.run_locked(run_id)
            if run is None or run.status in {"succeeded", "failed", "cancelled"}:
                return
            session = self.session.get(ConversationSession, run.session_id)
            if session is None:
                return
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.completed_at = utc_now()
                self._emit(session, run=run, event_type="run.cancelled", payload={})
                return
            self._mark_failed(run, session, category, code)

    def _mark_failed(
        self, run: AgentRun, session: ConversationSession, category: str, code: str
    ) -> None:
        run.status = "failed"
        run.failure_category = category[:64]
        run.failure_code = code[:128]
        run.completed_at = utc_now()
        self._emit(
            session,
            run=run,
            event_type="run.failed",
            payload={"failure_category": run.failure_category, "failure_code": run.failure_code},
        )

    @staticmethod
    def _valid_response(run: AgentRun, response: object) -> bool:
        if not isinstance(response, GenerationResponse):
            return False
        if response.request_id != run.model_request_id:
            return False
        try:
            expected = route_model(
                Capability.CHAT,
                frozenset({Modality.TEXT}),
                requested_model=run.requested_model or "fast",
            )
        except ModelGatewayError:
            return False
        if (
            response.model.provider is not expected.provider
            or response.model.model_id != expected.model_id
            or response.model.digest != expected.digest
        ):
            return False
        if (
            not isinstance(response.text, str)
            or not response.text.strip()
            or len(response.text) > 4000
        ):
            return False
        if (
            not isinstance(response.finish_reason, str)
            or not 1 <= len(response.finish_reason) <= 64
        ):
            return False
        usage = response.usage
        return not response.tool_proposals and not any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (usage.prompt_tokens, usage.output_tokens, usage.total_tokens)
        )

    def _event_envelope(self, event: RunEvent) -> EventEnvelope:
        data = dict(event.payload_json)
        if event.event_type == "assistant.message.ready":
            message_id = data.get("assistant_message_id")
            if isinstance(message_id, str):
                message = self.session.get(ConversationMessage, UUID(message_id))
                if message is not None:
                    data["content"] = message.content
        return EventEnvelope(
            sequence=event.sequence,
            event_type=event.event_type,
            conversation_id=event.conversation_id,
            session_id=event.session_id,
            run_id=event.run_id,
            occurred_at=event.occurred_at,
            data=data,
        )

    @staticmethod
    def to_conversation_response(row: Conversation) -> ConversationResponse:
        return ConversationResponse.model_validate(row, from_attributes=True)

    @staticmethod
    def to_session_response(row: ConversationSession) -> ConversationSessionResponse:
        return ConversationSessionResponse.model_validate(row, from_attributes=True)

    @staticmethod
    def to_message_response(row: ConversationMessage) -> MessageResponse:
        return MessageResponse.model_validate(row, from_attributes=True)

    @staticmethod
    def to_run_response(row: AgentRun) -> RunResponse:
        return RunResponse.model_validate(row, from_attributes=True)
