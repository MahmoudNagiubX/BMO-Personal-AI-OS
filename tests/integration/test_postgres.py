from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from personal_ai_os.app import create_app
from personal_ai_os.core.config import get_settings

pytestmark = pytest.mark.integration
EXPECTED_REVISION = "20260803_0001"


@pytest.fixture
def test_database_url() -> str:
    value = os.environ.get("BMO_TEST_DATABASE_URL")
    if not value:
        pytest.skip("BMO_TEST_DATABASE_URL is not set")
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+psycopg":
        pytest.fail("BMO_TEST_DATABASE_URL must use postgresql+psycopg")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("integration tests only accept a localhost PostgreSQL URL")
    if not parsed.path or parsed.path == "/":
        pytest.fail("BMO_TEST_DATABASE_URL must include a database name")
    return value


def test_postgresql_connection_and_vector_extension(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            extension = connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
            assert extension == "vector"
    finally:
        engine.dispose()


def test_alembic_head_is_applied(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == EXPECTED_REVISION
    finally:
        engine.dispose()


def test_readiness_uses_real_database(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BMO_ENVIRONMENT", "test")
    monkeypatch.setenv("BMO_DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
    finally:
        app.state.database_engine.dispose()
        get_settings.cache_clear()
