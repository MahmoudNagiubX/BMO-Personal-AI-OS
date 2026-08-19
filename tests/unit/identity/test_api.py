from __future__ import annotations

import logging
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from personal_ai_os.app import create_app
from personal_ai_os.core.config import get_settings
from personal_ai_os.identity.contracts import EnrollmentGrant
from personal_ai_os.identity.service import IdentityService
from tests.unit.identity.conftest import ALL_SCOPES, NOW


@pytest.fixture
def client_and_factory(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, sessionmaker], None, None]:
    monkeypatch.setenv("BMO_ENVIRONMENT", "test")
    get_settings.cache_clear()
    app = create_app()
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    app.state.database_session_factory = factory
    with TestClient(app) as client:
        yield client, factory
    get_settings.cache_clear()


def issue_enrollment(factory: sessionmaker, *, scopes: list[str]) -> tuple[str, object]:
    with factory() as session:
        service = IdentityService(session, clock=lambda: NOW)
        owner = service.bootstrap_owner("Synthetic owner")
        issued = service.create_enrollment(
            EnrollmentGrant(
                owner_id=owner.id,
                display_name="Synthetic client",
                device_kind="windows_client",
                platform="windows",
                scopes=scopes,
                capabilities=["system.health"],
            )
        )
    return issued.code, owner.id


def redeem(client: TestClient, code: str) -> str:
    response = client.post("/api/v1/enrollment/redeem", json={"code": code})
    assert response.status_code == 201
    return str(response.json()["credential"])


def test_redeem_accepts_no_device_controlled_authority(
    client_and_factory: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = client_and_factory
    code, _ = issue_enrollment(factory, scopes=ALL_SCOPES)

    response = client.post(
        "/api/v1/enrollment/redeem",
        json={"code": code, "scopes": ["admin"], "capabilities": ["shell.unrestricted"]},
    )

    assert response.status_code == 422
    credential = redeem(client, code)
    self_response = client.get(
        "/api/v1/devices/me", headers={"Authorization": f"Bearer {credential}"}
    )
    assert self_response.status_code == 200
    assert self_response.json()["approved_scopes"] == sorted(ALL_SCOPES)
    assert self_response.json()["approved_capabilities"] == ["system.health"]


def test_bearer_auth_scope_heartbeat_and_rotation(
    client_and_factory: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = client_and_factory
    code, _ = issue_enrollment(factory, scopes=ALL_SCOPES)
    credential = redeem(client, code)
    headers = {"Authorization": f"Bearer {credential}"}

    assert client.get("/api/v1/devices/me", headers=headers).status_code == 200
    heartbeat = client.post(
        "/api/v1/devices/me/heartbeat",
        headers=headers,
        json={"software_version": "1.0.0", "reported_capabilities": ["system.health"]},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["reported_capabilities"] == ["system.health"]
    denied = client.post(
        "/api/v1/devices/me/heartbeat",
        headers=headers,
        json={"reported_capabilities": ["shell.unrestricted"]},
    )
    assert denied.status_code == 403

    rotated = client.post("/api/v1/devices/me/credentials/rotate", headers=headers)
    assert rotated.status_code == 200
    replacement = rotated.json()["credential"]
    assert client.get("/api/v1/devices/me", headers=headers).status_code == 401
    assert (
        client.get(
            "/api/v1/devices/me",
            headers={"Authorization": f"Bearer {replacement}"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic opaque", "Bearer malformed", f"Bearer {'u' * 16}.{'s' * 43}"],
)
def test_authentication_failures_are_generic(
    client_and_factory: tuple[TestClient, sessionmaker], authorization: str | None
) -> None:
    client, _ = client_and_factory
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.get("/api/v1/devices/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid device credential"}


def test_missing_scope_is_typed_forbidden(
    client_and_factory: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = client_and_factory
    code, _ = issue_enrollment(factory, scopes=["device.self.read"])
    credential = redeem(client, code)

    response = client.post(
        "/api/v1/devices/me/heartbeat",
        headers={"Authorization": f"Bearer {credential}"},
        json={"reported_capabilities": []},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient scope"}


def test_authentication_secret_is_absent_from_errors_and_logs(
    client_and_factory: tuple[TestClient, sessionmaker], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = client_and_factory
    raw = f"{'u' * 16}.{'z' * 43}"
    caplog.set_level(logging.INFO)

    response = client.get("/api/v1/devices/me", headers={"Authorization": f"Bearer {raw}"})

    assert response.status_code == 401
    assert raw not in response.text
    assert raw not in caplog.text
