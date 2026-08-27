from __future__ import annotations

import io
import json
from typing import Any

import pytest

from personal_ai_os.voice.core_transport import AuthenticatedCoreHttpTransport


class Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def __enter__(self) -> io.BytesIO:
        return io.BytesIO(json.dumps(self._payload).encode())

    def __exit__(self, *args: object) -> None:
        return None


def test_core_transport_requires_bearer_and_rejects_public_hosts() -> None:
    with pytest.raises(ValueError, match="loopback/private"):
        AuthenticatedCoreHttpTransport(
            base_url="https://203.0.113.10:8000", bearer_token=lambda: "secret", session_id="s"
        )
    transport = AuthenticatedCoreHttpTransport(
        base_url="http://192.168.1.25:8000",
        allow_private_network=True,
        bearer_token=lambda: "",
        session_id="s",
    )
    assert transport.available() is False


def test_core_transport_polls_existing_authority_and_returns_assistant_text() -> None:
    payloads = iter(
        [
            {
                "message": {"content": "user text"},
                "run": {
                    "id": "run-1",
                    "conversation_id": "conversation-1",
                    "model_request_id": "request-1",
                },
            },
            {"id": "run-1", "status": "succeeded"},
            [
                {"run_id": "run-1", "role": "user", "content": "user text"},
                {"run_id": "run-1", "role": "assistant", "content": "reply"},
            ],
        ]
    )

    def opener(request: object, *, timeout: float) -> Response:
        del request, timeout
        return Response(next(payloads))

    transport = AuthenticatedCoreHttpTransport(
        base_url="http://127.0.0.1:8000",
        bearer_token=lambda: "opaque-token",
        session_id="session-1",
        poll_interval_seconds=0.001,
        opener=opener,
    )
    response = transport.send("hello", client_message_id="message-1")
    assert response.request_id == "request-1"
    assert response.text == "reply"
