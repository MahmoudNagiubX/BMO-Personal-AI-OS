"""Fail-closed startup reconciliation readiness for Phase 8 tool operations."""

from __future__ import annotations

import logging
from threading import Lock

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_os.tools.service import ToolPlatformService

LOGGER = logging.getLogger(__name__)


class ToolReconciliationGate:
    """Retry interrupted/stale tool reconciliation with one fresh session at a time."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._ready = False
        self._deferred = False
        self._attempts = 0

    @property
    def ready(self) -> bool:
        """Whether tool reconciliation has completed successfully in this process."""
        return self._ready

    @property
    def deferred(self) -> bool:
        """Whether the last tool reconciliation attempt was unavailable."""
        return self._deferred

    @property
    def attempts(self) -> int:
        """Return the number of serialized reconciliation attempts."""
        return self._attempts

    def attempt(self, session_factory: sessionmaker[Session]) -> bool:
        """Make one startup/readiness tool reconciliation attempt."""
        with self._lock:
            if self._ready:
                return True
            self._attempts += 1
            try:
                with session_factory() as session:
                    ToolPlatformService(session).reconcile_stale_executing()
            except Exception:
                # Do not expose database URLs, driver messages, or other exception data.
                self._deferred = True
                LOGGER.error("tool reconciliation deferred")
                return False
            self._ready = True
            self._deferred = False
            return True

    def ensure_ready(self, session_factory: sessionmaker[Session]) -> bool:
        """Ensure stale executing calls are reconciled before protected work."""
        return self.attempt(session_factory)


def sync_tool_gate_state(application: FastAPI, gate: ToolReconciliationGate) -> None:
    """Expose redacted gate state for readiness diagnostics and tests."""
    state = application.state
    state.tool_reconciliation_ready = gate.ready
    state.tool_reconciliation_deferred = gate.deferred


__all__ = ["ToolReconciliationGate", "sync_tool_gate_state"]
