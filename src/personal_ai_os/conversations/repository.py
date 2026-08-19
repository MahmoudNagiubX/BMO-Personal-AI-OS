"""Small SQLAlchemy repository for the Phase 7 conversation domain."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from personal_ai_os.conversations.models import (
    AgentRun,
    Conversation,
    ConversationMessage,
    ConversationSession,
    RunEvent,
)


class ConversationRepository:
    """Keep query details out of the conversation service and API routes."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *rows: object) -> None:
        self.session.add_all(rows)

    def flush(self) -> None:
        self.session.flush()

    def conversation(self, owner_id: UUID, conversation_id: UUID) -> Conversation | None:
        return self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.owner_id == owner_id,
            )
        )

    def conversations(self, owner_id: UUID, *, limit: int, offset: int) -> list[Conversation]:
        statement = (
            select(Conversation)
            .where(Conversation.owner_id == owner_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def session_for_owner(self, owner_id: UUID, session_id: UUID) -> ConversationSession | None:
        return self.session.scalar(
            select(ConversationSession).where(
                ConversationSession.id == session_id,
                ConversationSession.owner_id == owner_id,
            )
        )

    def session_locked(self, session_id: UUID) -> ConversationSession | None:
        return self.session.scalar(
            select(ConversationSession)
            .where(ConversationSession.id == session_id)
            .with_for_update()
        )

    def message_by_client_id(
        self,
        conversation_id: UUID,
        device_id: UUID,
        client_message_id: UUID,
    ) -> ConversationMessage | None:
        return self.session.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.author_device_id == device_id,
                ConversationMessage.client_message_id == client_message_id,
            )
        )

    def next_message_ordinal(self, conversation_id: UUID) -> int:
        value = self.session.scalar(
            select(func.max(ConversationMessage.ordinal)).where(
                ConversationMessage.conversation_id == conversation_id
            )
        )
        return int(value or 0) + 1

    def active_run(self, conversation_id: UUID) -> AgentRun | None:
        return self.session.scalar(
            select(AgentRun)
            .where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.status.in_(("queued", "running", "cancel_requested")),
            )
            .order_by(AgentRun.created_at, AgentRun.id)
        )

    def run(self, run_id: UUID) -> AgentRun | None:
        return self.session.get(AgentRun, run_id)

    def run_locked(self, run_id: UUID) -> AgentRun | None:
        statement: Select[tuple[AgentRun]] = (
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self.session.scalar(statement)

    def runs(self, owner_id: UUID, conversation_id: UUID, *, limit: int) -> list[AgentRun]:
        statement = (
            select(AgentRun)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(
                AgentRun.conversation_id == conversation_id,
                Conversation.owner_id == owner_id,
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def messages(
        self, owner_id: UUID, conversation_id: UUID, *, limit: int
    ) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessage)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                Conversation.owner_id == owner_id,
            )
            .order_by(ConversationMessage.ordinal)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def conversation_messages(self, conversation_id: UUID) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.ordinal)
        )
        return list(self.session.scalars(statement))

    def event(self, event_id: UUID) -> RunEvent | None:
        return self.session.get(RunEvent, event_id)

    def events_after(self, session_id: UUID, after_sequence: int, *, limit: int) -> list[RunEvent]:
        statement = (
            select(RunEvent)
            .where(RunEvent.session_id == session_id, RunEvent.sequence > after_sequence)
            .order_by(RunEvent.sequence)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def next_event_sequence(self, session_id: UUID) -> int:
        value = self.session.scalar(
            select(func.max(RunEvent.sequence)).where(RunEvent.session_id == session_id)
        )
        return int(value or 0) + 1

    def nonterminal_runs(self) -> list[AgentRun]:
        return list(
            self.session.scalars(
                select(AgentRun)
                .where(AgentRun.status.in_(("queued", "running", "cancel_requested")))
                .order_by(AgentRun.created_at, AgentRun.id)
                .with_for_update()
            )
        )
