"""Fail-closed Phase 8 platform errors."""


class ToolPlatformError(Exception):
    """Base class for deterministic tool-platform failures."""

    def __init__(self, code: str, message: str = "tool request rejected") -> None:
        super().__init__(message)
        self.code = code


class ToolNotFoundError(ToolPlatformError):
    """The exact name/version is not present in the static catalog."""


class ToolSchemaError(ToolPlatformError):
    """Tool input or output failed its strict schema."""


class ToolDeniedError(ToolPlatformError):
    """A deterministic policy check denied the action."""


class ToolConflictError(ToolPlatformError):
    """The idempotency or state binding conflicts with existing authority."""


class ApprovalError(ToolPlatformError):
    """An approval is expired, replayed, cancelled, or otherwise invalid."""


class ToolUnavailableError(ToolPlatformError):
    """The static availability policy is not currently usable."""


class ToolBudgetError(ToolPlatformError):
    """A run/action/approval budget or rate limit was exhausted."""
