"""Bounded background execution for synchronous ModelGateway calls."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.model_gateway import ModelGateway


class ConversationExecutor:
    """Use fresh database sessions and never block the ASGI event loop."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway_factory: Callable[[], ModelGateway],
    ) -> None:
        self._session_factory = session_factory
        self._gateway_factory = gateway_factory
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bmo-conversation")

    def submit(self, run_id: UUID) -> None:
        """Schedule one run; the run state remains durable if the process stops."""

        self._pool.submit(self._execute, run_id)

    def _execute(self, run_id: UUID) -> None:
        with self._session_factory() as session:
            ConversationService(session).execute_run(run_id, self._gateway_factory())

    def shutdown(self) -> None:
        """Stop accepting background work during application shutdown."""

        self._pool.shutdown(wait=True, cancel_futures=False)
