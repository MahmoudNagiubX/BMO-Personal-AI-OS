"""Shared local-only database session setup for Phase 6 administration."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from personal_ai_os.core.config import get_settings
from personal_ai_os.db.engine import create_engine_for_settings, create_session_factory


@contextmanager
def identity_session() -> Generator[Session, None, None]:
    """Yield a local administrative session without printing connection settings."""

    engine = create_engine_for_settings(get_settings())
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            yield session
    finally:
        engine.dispose()
