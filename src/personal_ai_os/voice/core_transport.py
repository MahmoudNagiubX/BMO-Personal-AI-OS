"""Authenticated transport adapter for the existing Phase 7 Core API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from ipaddress import ip_address
from time import monotonic, sleep
from typing import Any
from urllib.parse import urlsplit

from personal_ai_os.voice.contracts import CoreResponse


class CoreTransportUnavailable(RuntimeError):
    """Core is unavailable; the voice client has no local authority fallback."""


class AuthenticatedCoreHttpTransport:
    """Send text only to authenticated Core conversation endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: Callable[[], str],
        session_id: str,
        timeout_seconds: float = 30.0,
        allow_private_network: bool = False,
        poll_interval_seconds: float = 0.25,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("voice Core transport must use a bounded HTTP origin")
        if parsed.hostname is None:
            raise ValueError("voice Core transport requires an IP literal")
        try:
            address = ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("voice Core transport requires an IP literal") from exc
        if not address.is_loopback and not (allow_private_network and address.is_private):
            raise ValueError("voice Core transport must remain loopback/private-LAN only")
        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("Core timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._opener = opener or urllib.request.urlopen

    def available(self) -> bool:
        return bool(self._bearer_token())

    def send(self, text: str, *, client_message_id: str) -> CoreResponse:
        token = self._bearer_token()
        if not token:
            raise CoreTransportUnavailable("Core credential is unavailable")
        body = json.dumps(
            {"client_message_id": client_message_id, "content": text, "model": "fast"}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/conversation-sessions/{self.session_id}/messages",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            payload = self._open_json(request)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise CoreTransportUnavailable("Core request failed") from exc
        if not isinstance(payload, dict):
            raise CoreTransportUnavailable("Core response was malformed")
        run = payload.get("run")
        if not isinstance(run, dict):
            raise CoreTransportUnavailable("Core response lacked sanitized lifecycle data")
        run_id = run.get("id")
        conversation_id = run.get("conversation_id")
        if not isinstance(run_id, str) or not isinstance(conversation_id, str):
            raise CoreTransportUnavailable("Core response lacked lifecycle identifiers")
        deadline = monotonic() + self.timeout_seconds
        while monotonic() < deadline:
            current = self._get_json(f"/api/v1/agent-runs/{run_id}", token)
            status = current.get("status")
            if status == "succeeded":
                messages = self._get_json(
                    f"/api/v1/conversations/{conversation_id}/messages?limit=20", token
                )
                if not isinstance(messages, list):
                    raise CoreTransportUnavailable("Core messages response was malformed")
                for message in reversed(messages):
                    if (
                        isinstance(message, dict)
                        and message.get("run_id") == run_id
                        and message.get("role") == "assistant"
                        and isinstance(message.get("content"), str)
                    ):
                        request_id = run.get("model_request_id") or run_id
                        return CoreResponse(request_id=str(request_id), text=message["content"])
                raise CoreTransportUnavailable("Core completed run without assistant message")
            if status in {"failed", "cancelled"}:
                raise CoreTransportUnavailable("Core run did not produce a response")
            sleep(self.poll_interval_seconds)
        raise CoreTransportUnavailable("Core response timed out")

    def _get_json(self, path: str, token: str) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            return self._open_json(request)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise CoreTransportUnavailable("Core status request failed") from exc

    def _open_json(self, request: urllib.request.Request) -> Any:
        with self._opener(request, timeout=self.timeout_seconds) as response:
            return json.load(response)


__all__ = ["AuthenticatedCoreHttpTransport", "CoreTransportUnavailable"]
