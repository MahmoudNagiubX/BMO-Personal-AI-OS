from __future__ import annotations

import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from personal_ai_os.api.routes.health import get_database_health
from personal_ai_os.app import create_app
from personal_ai_os.core.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("BMO_DATABASE_URL", raising=False)
    monkeypatch.delenv("BMO_BUILD_SHA", raising=False)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_application_factory_creates_health_only_api(client: TestClient) -> None:
    live_response = client.get("/health/live")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "ok"}
    assert client.get("/agent").status_code == 404


def test_version_endpoint_has_only_build_identity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BMO_BUILD_SHA", "abc123")
    get_settings.cache_clear()

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "name": "BMO Personal AI OS",
        "version": "0.0.0",
        "build_sha": "abc123",
    }
    body = response.text
    assert "username" not in body
    assert "127.0.0.1" not in body
    assert "password" not in body


def test_readiness_success_can_use_a_replaced_health_check(client: TestClient) -> None:
    app = client.app

    def healthy(_: float) -> None:
        return None

    app.dependency_overrides[get_database_health] = lambda: healthy
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_failure_is_generic_and_redacted(client: TestClient) -> None:
    app = client.app

    def unavailable(_: float) -> None:
        raise RuntimeError("postgresql+psycopg://bmo:super-secret@127.0.0.1:5432/bmo")

    app.dependency_overrides[get_database_health] = lambda: unavailable
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    assert "super-secret" not in response.text
    assert "postgresql" not in response.text


def test_application_creation_does_not_duplicate_json_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BMO_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    first = create_app()
    second = create_app()

    import logging

    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_bmo_json_handler", False)
    ]
    assert len(handlers) == 1
    with TestClient(first), TestClient(second):
        pass
    get_settings.cache_clear()


def test_application_shutdown_disposes_engine_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BMO_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    dispose = Mock(wraps=app.state.database_engine.dispose)
    monkeypatch.setattr(app.state.database_engine, "dispose", dispose)

    with TestClient(app):
        pass

    dispose.assert_called_once_with()
    get_settings.cache_clear()


def test_generated_correlation_id_is_returned(client: TestClient) -> None:
    response = client.get("/health/live")

    correlation_id = response.headers["x-correlation-id"]
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", correlation_id)


def test_supplied_valid_correlation_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "test.request-01"})

    assert response.headers["x-correlation-id"] == "test.request-01"
