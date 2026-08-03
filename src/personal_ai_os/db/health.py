"""Replaceable database health check implementation."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Engine

from personal_ai_os.db.engine import ping_database

DatabaseHealthCheck = Callable[[float], None]


def create_database_health_check(engine: Engine) -> DatabaseHealthCheck:
    """Build a health function around an engine without connecting yet."""

    def check(timeout_seconds: float) -> None:
        ping_database(engine, timeout_seconds)

    return check
