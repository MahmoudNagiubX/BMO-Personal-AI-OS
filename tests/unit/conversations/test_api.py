from __future__ import annotations

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from personal_ai_os.app import create_app
from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.core.config import get_settings
from personal_ai_os.identity.contracts import PHASE_7_SCOPES, EnrollmentGrant
from personal_ai_os.identity.models import Owner
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.model_gateway import ModelGateway
from tests.unit.conversations.test_service import ALL_PHASE_7_SCOPES
from tests.unit.identity.conftest import NOW
from tests.unit.model_gateway.fakes import FakeProvider


class RecordingExecutor:
    """Deterministic test executor; tests invoke recorded runs explicitly."""

    def __init__(self) -> None:
        self.run_ids: list[object] = []

    def submit(self, run_id: object) -> None:
        self.run_ids.append(run_id)

    def shutdown(self) -> None:
        return None


@pytest.fixture
def phase7_client(
    sqlite_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, sessionmaker, RecordingExecutor, FakeProvider], None, None]:
    monkeypatch.setenv("BMO_ENVIRONMENT", "test")
    get_settings.cache_clear()
    app = create_app()
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    app.state.database_session_factory = factory
    provider = FakeProvider()
    app.state.model_gateway = ModelGateway(provider)
    app.state.conversation_executor.shutdown()
    executor = RecordingExecutor()
    app.state.conversation_executor = executor
    with TestClient(app) as client:
        yield client, factory, executor, provider
    get_settings.cache_clear()


def issue_credential(
    factory: sessionmaker, *, scopes: list[str], owner_id: UUID | None = None
) -> tuple[str, UUID]:
    with factory() as session:
        service = IdentityService(session, clock=lambda: NOW)
        if owner_id is None:
            owner = service.bootstrap_owner("Synthetic API owner")
            owner_id = owner.id
        else:
            owner = session.get(Owner, owner_id)
            assert owner is not None
            owner_uuid = owner.id
            session.rollback()
            owner_id = owner_uuid
        assert owner is not None
        enrollment = service.create_enrollment(
            EnrollmentGrant(
                owner_id=owner_id,
                display_name="Synthetic API client",
                device_kind="windows_client",
                platform="windows",
                scopes=scopes,
                capabilities=[],
            )
        )
        return service.redeem_enrollment(enrollment.code).raw, owner_id


def test_rest_submission_idempotency_history_and_bounded_validation(
    phase7_client: tuple[TestClient, sessionmaker, RecordingExecutor, FakeProvider],
) -> None:
    client, factory, executor, provider = phase7_client
    credential, _ = issue_credential(factory, scopes=ALL_PHASE_7_SCOPES)
    headers = {"Authorization": f"Bearer {credential}"}

    created = client.post("/api/v1/conversations", headers=headers, json={"title": "API test"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    opened = client.post(
        f"/api/v1/conversations/{conversation_id}/sessions", headers=headers, json={}
    )
    assert opened.status_code == 201
    session_id = opened.json()["id"]
    client_message_id = str(uuid4())
    submission = client.post(
        f"/api/v1/conversation-sessions/{session_id}/messages",
        headers=headers,
        json={"client_message_id": client_message_id, "content": "bounded API message"},
    )
    assert submission.status_code == 202, submission.text
    assert len(executor.run_ids) == 1
    run_id = submission.json()["run"]["id"]
    with factory() as session:
        ConversationService(session).execute_run(UUID(run_id), ModelGateway(provider))

    replay = client.post(
        f"/api/v1/conversation-sessions/{session_id}/messages",
        headers=headers,
        json={"client_message_id": client_message_id, "content": "bounded API message"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["run"]["status"] == "succeeded"
    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]
    runs = client.get(f"/api/v1/conversations/{conversation_id}/runs", headers=headers)
    assert runs.status_code == 200
    assert runs.json()[0]["id"] == run_id

    invalid = client.post(
        f"/api/v1/conversation-sessions/{session_id}/messages",
        headers=headers,
        json={"client_message_id": str(uuid4()), "content": "X" * 4001},
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "invalid request"}
    assert "X" * 50 not in invalid.text


def test_rest_auth_and_scope_boundaries(
    phase7_client: tuple[TestClient, sessionmaker, RecordingExecutor, FakeProvider],
) -> None:
    client, factory, _, _ = phase7_client
    assert client.get("/api/v1/conversations").status_code == 401
    device_only, owner_id = issue_credential(factory, scopes=["device.self.read"])
    denied = client.get("/api/v1/conversations", headers={"Authorization": f"Bearer {device_only}"})
    assert denied.status_code == 403
    stream_only, _ = issue_credential(
        factory,
        owner_id=owner_id,
        scopes=sorted(PHASE_7_SCOPES - {"conversation.write", "conversation.read"}),
    )
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(
            "/api/v1/conversation-sessions/00000000-0000-0000-0000-000000000001/events",
            headers={"Authorization": f"Bearer {stream_only}"},
        ),
    ):
        pass
    assert error.value.code == 4403


def test_websocket_replays_sanitized_events_and_assistant_content(
    phase7_client: tuple[TestClient, sessionmaker, RecordingExecutor, FakeProvider],
) -> None:
    client, factory, _, provider = phase7_client
    credential, _ = issue_credential(factory, scopes=ALL_PHASE_7_SCOPES)
    headers = {"Authorization": f"Bearer {credential}"}
    conversation = client.post("/api/v1/conversations", headers=headers, json={}).json()
    session = client.post(
        f"/api/v1/conversations/{conversation['id']}/sessions", headers=headers, json={}
    ).json()
    submitted = client.post(
        f"/api/v1/conversation-sessions/{session['id']}/messages",
        headers=headers,
        json={"client_message_id": str(uuid4()), "content": "websocket content"},
    ).json()
    assert "run" in submitted, submitted
    with factory() as db_session:
        ConversationService(db_session).execute_run(
            UUID(submitted["run"]["id"]), ModelGateway(provider)
        )

    received: list[dict[str, object]] = []
    with client.websocket_connect(
        f"/api/v1/conversation-sessions/{session['id']}/events?after_sequence=1",
        headers=headers,
    ) as websocket:
        for _ in range(8):
            event = websocket.receive_json()
            received.append(event)
            if event["event_type"] == "assistant.message.ready":
                break
    sequences = [int(event["sequence"]) for event in received]
    assert sequences == sorted(sequences)
    assert all(sequence > 1 for sequence in sequences)
    ready = next(event for event in received if event["event_type"] == "assistant.message.ready")
    assert ready["data"]["content"] == "synthetic response"
    assert "Authorization" not in str(received)
