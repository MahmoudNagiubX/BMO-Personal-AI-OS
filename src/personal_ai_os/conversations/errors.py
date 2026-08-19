"""Typed failures for the Phase 7 conversation boundary."""


class ConversationError(Exception):
    """Base conversation-domain error."""


class ConversationNotFoundError(ConversationError):
    """The requested conversation is not visible to this owner."""


class ConversationSessionNotFoundError(ConversationError):
    """The requested session is not visible to this owner/device."""


class AgentRunNotFoundError(ConversationError):
    """The requested run is not visible to this owner/device."""


class ConversationBusyError(ConversationError):
    """A conversation already has one non-terminal run."""


class IdempotencyConflictError(ConversationError):
    """A client idempotency key was reused for different content."""


class SessionClosedError(ConversationError):
    """A closed session cannot accept new work."""


class RunStateError(ConversationError):
    """A run state transition is not valid."""
