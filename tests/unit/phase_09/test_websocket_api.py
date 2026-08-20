from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from personal_ai_os.app import create_app
from personal_ai_os.core.config import get_settings
from personal_ai_os.db.base import Base
from personal_ai_os.identity.contracts import EnrollmentGrant
from personal_ai_os.identity.models import Owner
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.satellites.windows.contracts import PROTOCOL_VERSION

SCOPES = [
    "device.self.read",
    "device.heartbeat.write",
    "device.capabilities.report",
    "device.credential.rotate",
    "satellite.connect",
]
CAPABILITIES = ["windows.telemetry.read", "windows.files.search"]


@pytest.fixture
def sqlite_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def satellite_client(
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


def _credential(factory: sessionmaker) -> tuple[str, object]:
    with factory() as session:
        service = IdentityService(session)
        owner = service.bootstrap_owner("Synthetic Phase 9 owner")
        enrollment = service.create_enrollment(
            EnrollmentGrant(
                owner_id=owner.id,
                display_name="Synthetic Windows satellite",
                device_kind="windows_satellite",
                platform="windows",
                software_version="phase09-test",
                scopes=SCOPES,
                capabilities=CAPABILITIES,
            )
        )
        issued = service.redeem_enrollment(enrollment.code)
        return issued.raw, issued.device_id


def _satellite_credential(
    factory: sessionmaker,
    *,
    scopes: list[str],
    disable_owner: bool = False,
) -> str:
    with factory() as session:
        service = IdentityService(session)
        owner = service.bootstrap_owner("Synthetic Phase 9 owner")
        enrollment = service.create_enrollment(
            EnrollmentGrant(
                owner_id=owner.id,
                display_name="Synthetic Windows satellite",
                device_kind="windows_satellite",
                platform="windows",
                scopes=scopes,
                capabilities=CAPABILITIES,
            )
        )
        credential = service.redeem_enrollment(enrollment.code).raw
        if disable_owner:
            with session.begin():
                row = session.scalar(select(Owner).where(Owner.id == owner.id))
                assert row is not None
                row.status = "disabled"
        return credential


def _hello(capabilities: list[str] | None = None) -> dict[str, object]:
    return {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION,
        "connection_id": "69eb0cc2-b079-43a8-8931-88037090548c",
        "software_version": "phase09-test",
        "capabilities": CAPABILITIES if capabilities is None else capabilities,
        "sent_at": datetime.now(UTC).isoformat(),
    }


def test_websocket_requires_exact_device_identity_scope_and_capabilities(
    satellite_client: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = satellite_client
    credential, _ = _credential(factory)
    with client.websocket_connect(
        "/api/v1/satellites/windows/connect",
        headers={"Authorization": f"Bearer {credential}"},
    ) as websocket:
        websocket.send_json(_hello())
        welcome = websocket.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["protocol_version"] == PROTOCOL_VERSION
        assert welcome["max_in_flight_commands"] == 2

    with (
        pytest.raises(WebSocketDisconnect) as denied,
        client.websocket_connect(
            "/api/v1/satellites/windows/connect",
            headers={"Authorization": f"Bearer {credential}"},
        ) as websocket,
    ):
        websocket.send_json(_hello(["windows.shell.unrestricted"]))
        websocket.receive_json()
    assert denied.value.code == 4400


def test_open_socket_revalidates_revocation_on_next_frame(
    satellite_client: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = satellite_client
    credential, device_id = _credential(factory)
    with client.websocket_connect(
        "/api/v1/satellites/windows/connect",
        headers={"Authorization": f"Bearer {credential}"},
    ) as websocket:
        websocket.send_json(_hello())
        welcome = websocket.receive_json()
        with factory() as session:
            IdentityService(session).revoke_device(device_id)
        websocket.send_json(
            {
                "type": "heartbeat",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": welcome["session_id"],
                "sequence": 1,
                "sent_at": datetime.now(UTC).isoformat(),
            }
        )
        with pytest.raises(WebSocketDisconnect) as revoked:
            websocket.receive_json()
        assert revoked.value.code == 4401


def test_websocket_rejects_missing_bearer_and_wrong_device_kind(
    satellite_client: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = satellite_client
    with (
        pytest.raises(WebSocketDisconnect) as missing,
        client.websocket_connect("/api/v1/satellites/windows/connect"),
    ):
        pass
    assert missing.value.code == 4401

    with factory() as session:
        service = IdentityService(session)
        owner = service.bootstrap_owner("Synthetic Phase 9 owner")
        enrollment = service.create_enrollment(
            EnrollmentGrant(
                owner_id=owner.id,
                display_name="Ordinary Windows client",
                device_kind="windows_client",
                platform="windows",
                scopes=SCOPES,
                capabilities=CAPABILITIES,
            )
        )
        credential = service.redeem_enrollment(enrollment.code).raw
    with (
        pytest.raises(WebSocketDisconnect) as wrong_kind,
        client.websocket_connect(
            "/api/v1/satellites/windows/connect",
            headers={"Authorization": f"Bearer {credential}"},
        ),
    ):
        pass
    assert wrong_kind.value.code == 4403


@pytest.mark.parametrize("disabled_owner", [False, True])
def test_websocket_rejects_missing_scope_and_disabled_owner(
    satellite_client: tuple[TestClient, sessionmaker], disabled_owner: bool
) -> None:
    client, factory = satellite_client
    scopes = (
        SCOPES if disabled_owner else [scope for scope in SCOPES if scope != "satellite.connect"]
    )
    credential = _satellite_credential(
        factory,
        scopes=scopes,
        disable_owner=disabled_owner,
    )
    expected = 4401 if disabled_owner else 4403
    with (
        pytest.raises(WebSocketDisconnect) as rejected,
        client.websocket_connect(
            "/api/v1/satellites/windows/connect",
            headers={"Authorization": f"Bearer {credential}"},
        ),
    ):
        pass
    assert rejected.value.code == expected


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        '{"type":"hello","type":"hello"}',
        '{"type":"hello","protocol_version":"future"}',
    ],
)
def test_websocket_rejects_malformed_duplicate_and_wrong_version_frames(
    satellite_client: tuple[TestClient, sessionmaker], payload: str
) -> None:
    client, factory = satellite_client
    credential, _ = _credential(factory)
    with client.websocket_connect(
        "/api/v1/satellites/windows/connect",
        headers={"Authorization": f"Bearer {credential}"},
    ) as websocket:
        websocket.send_text(payload)
        with pytest.raises(WebSocketDisconnect) as rejected:
            websocket.receive_json()
        assert rejected.value.code == 4400


def test_websocket_rejects_oversized_frame(
    satellite_client: tuple[TestClient, sessionmaker],
) -> None:
    client, factory = satellite_client
    credential, _ = _credential(factory)
    with client.websocket_connect(
        "/api/v1/satellites/windows/connect",
        headers={"Authorization": f"Bearer {credential}"},
    ) as websocket:
        websocket.send_text("x" * 16_385)
        with pytest.raises(WebSocketDisconnect) as rejected:
            websocket.receive_json()
        assert rejected.value.code == 4400
