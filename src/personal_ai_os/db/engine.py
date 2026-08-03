"""SQLAlchemy 2 engine and session foundation."""

from __future__ import annotations

import math

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from personal_ai_os.core.config import Settings


def create_engine_for_settings(settings: Settings) -> Engine:
    """Create a lazy PostgreSQL engine with bounded connection/query timeouts."""

    timeout_milliseconds = max(1, math.ceil(settings.readiness_timeout_seconds * 1000))
    timeout_seconds = max(1, math.ceil(settings.readiness_timeout_seconds))
    return create_engine(
        settings.database_url,
        connect_args={
            "connect_timeout": timeout_seconds,
            "options": f"-c statement_timeout={timeout_milliseconds}",
        },
        echo=False,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the standard session factory for later domain consumers."""

    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def ping_database(engine: Engine, timeout_seconds: float = 1.0) -> None:
    """Run the minimal database ping used by readiness and integration tests."""

    del timeout_seconds
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()
