"""Fail-closed startup reconciliation readiness for Phase 7 operations."""

from __future__ import annotations

import logging
from threading import Lock

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_os.conversations.service import ConversationService

LOGGER = logging.getLogger(__name__)


class ConversationReconciliationGate:
    """Retry interrupted-run reconciliation with one fresh session at a time."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._ready = False
        self._deferred = False
        self._attempts = 0

    @property
    def ready(self) -> bool:
        """Whether reconciliation has completed successfully in this process."""

        return self._ready

    @property
    def deferred(self) -> bool:
        """Whether the last reconciliation attempt was unavailable."""

        return self._deferred

    @property
    def attempts(self) -> int:
        """Return the number of serialized reconciliation attempts."""

        return self._attempts

    def attempt(self, session_factory: sessionmaker[Session]) -> bool:
        """Make one startup/readiness reconciliation attempt."""

        with self._lock:
            if self._ready:
                return True
            self._attempts += 1
            try:
                with session_factory() as session:
                    ConversationService(session).reconcile_interrupted_runs()
            except Exception:
                # Do not expose database URLs, driver messages, or other exception data.
                self._deferred = True
                LOGGER.error("conversation reconciliation deferred")
                return False
            self._ready = True
            self._deferred = False
            return True

    def ensure_ready(self, session_factory: sessionmaker[Session]) -> bool:
        """Ensure stale nonterminal runs are reconciled before protected work."""

        return self.attempt(session_factory)


def sync_application_gate_state(application: FastAPI, gate: ConversationReconciliationGate) -> None:
    """Expose redacted gate state for readiness diagnostics and tests."""

    state = application.state
    state.conversation_reconciliation_ready = gate.ready
    state.conversation_reconciliation_deferred = gate.deferred


__all__ = ["ConversationReconciliationGate", "sync_application_gate_state"]
