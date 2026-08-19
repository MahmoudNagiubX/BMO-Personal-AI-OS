"""Minimal authenticated terminal client for Phase 7 text conversations."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from websockets.asyncio.client import ClientConnection, connect

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


@dataclass(slots=True)
class ClientState:
    """Non-secret local UI state; the credential is deliberately not stored here."""

    conversation_id: str | None = None
    session_id: str | None = None
    last_sequence: int = 0


def read_credential() -> str:
    """Load a credential from an environment variable or owner-readable local file."""

    value = os.environ.get("BMO_DEVICE_CREDENTIAL")
    if value:
        return value.strip()
    path_value = os.environ.get("BMO_DEVICE_CREDENTIAL_FILE")
    if path_value:
        return Path(path_value).read_text(encoding="utf-8").strip()
    raise RuntimeError("set BMO_DEVICE_CREDENTIAL or BMO_DEVICE_CREDENTIAL_FILE")


def parse_event(payload: Any, state: ClientState) -> dict[str, Any]:
    """Validate one strictly increasing lifecycle event without accepting secrets."""

    if not isinstance(payload, dict):
        raise ValueError("event envelope must be an object")
    sequence = payload.get("sequence")
    event_type = payload.get("event_type")
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence <= state.last_sequence
    ):
        raise ValueError("event sequence is not strictly increasing")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("event type is invalid")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("event data is invalid")
    state.last_sequence = sequence
    return {
        "sequence": sequence,
        "event_type": event_type,
        "run_id": payload.get("run_id"),
        "data": data,
    }


def request_json(
    base_url: str, method: str, path: str, credential: str, body: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    """Perform one bounded JSON request without including the credential in errors."""

    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=encoded,
        headers={
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return cast(dict[str, Any] | list[Any], json.loads(response.read()))
    except (HTTPError, URLError, TimeoutError) as error:
        del error
        raise RuntimeError("conversation API request failed") from None


async def consume_until_terminal(
    base_url: str,
    credential: str,
    websocket: ClientConnection,
    state: ClientState,
    run_id: str,
) -> str:
    """Display lifecycle events while allowing cancellation during generation."""

    receive_task = asyncio.create_task(websocket.recv())
    command_task = asyncio.create_task(asyncio.to_thread(input, "running> "))
    try:
        while True:
            done, _ = await asyncio.wait(
                (receive_task, command_task), return_when=asyncio.FIRST_COMPLETED
            )
            if command_task in done:
                command = command_task.result().strip()
                if command == "/quit":
                    print("detaching; the run remains truthful on the server")
                    return "detached"
                if command.startswith("/cancel"):
                    requested_run_id = command.removeprefix("/cancel").strip() or run_id
                    if requested_run_id != run_id:
                        print("cancel ignored: only the active run can be cancelled here")
                    else:
                        result = await asyncio.to_thread(
                            request_json,
                            base_url,
                            "POST",
                            f"/api/v1/agent-runs/{run_id}/cancel",
                            credential,
                            {},
                        )
                        print(json.dumps(result, ensure_ascii=False))
                command_task = asyncio.create_task(asyncio.to_thread(input, "running> "))

            if receive_task in done:
                raw = receive_task.result()
                event = parse_event(json.loads(raw), state)
                event_type = event["event_type"]
                data = event["data"]
                print(f"[{event['sequence']}] {event_type}")
                if event_type == "assistant.message.ready" and isinstance(data.get("content"), str):
                    print(f"assistant: {data['content']}")
                if event_type == "run.succeeded" and event.get("run_id") == run_id:
                    return "succeeded"
                if (
                    event_type in {"run.failed", "run.interrupted"}
                    and event.get("run_id") == run_id
                ):
                    return "failed"
                if event_type == "run.cancelled" and event.get("run_id") == run_id:
                    return "cancelled"
                receive_task = asyncio.create_task(websocket.recv())
    finally:
        for task in (receive_task, command_task):
            task.cancel()
        await asyncio.gather(receive_task, command_task, return_exceptions=True)


async def interactive(base_url: str, credential: str) -> None:
    """Run the small authenticated create/session/submit/history/cancel client."""

    state = ClientState()
    conversations = request_json(base_url, "GET", "/api/v1/conversations", credential)
    if not isinstance(conversations, list):
        raise RuntimeError("conversation list response is invalid")
    if conversations:
        state.conversation_id = str(conversations[0]["id"])
    else:
        created = request_json(
            base_url, "POST", "/api/v1/conversations", credential, {"title": None}
        )
        if not isinstance(created, dict):
            raise RuntimeError("conversation create response is invalid")
        state.conversation_id = str(created["id"])
    session = request_json(
        base_url,
        "POST",
        f"/api/v1/conversations/{state.conversation_id}/sessions",
        credential,
        {},
    )
    if not isinstance(session, dict):
        raise RuntimeError("conversation session response is invalid")
    state.session_id = str(session["id"])
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url += f"/api/v1/conversation-sessions/{state.session_id}/events"
    async with connect(
        ws_url,
        additional_headers={"Authorization": f"Bearer {credential}"},
    ) as websocket:
        print("BMO text client ready; /history, /cancel, /quit are available.")
        while True:
            prompt = await asyncio.to_thread(input, "you> ")
            if prompt == "/quit":
                return
            if prompt == "/history":
                history = request_json(
                    base_url,
                    "GET",
                    f"/api/v1/conversations/{state.conversation_id}/runs",
                    credential,
                )
                print(json.dumps(history, ensure_ascii=False))
                continue
            if prompt.startswith("/cancel "):
                run_id = prompt.removeprefix("/cancel ").strip()
                result = request_json(
                    base_url, "POST", f"/api/v1/agent-runs/{run_id}/cancel", credential, {}
                )
                print(json.dumps(result, ensure_ascii=False))
                continue
            if not prompt.strip():
                continue
            submission = request_json(
                base_url,
                "POST",
                f"/api/v1/conversation-sessions/{state.session_id}/messages",
                credential,
                {"client_message_id": str(uuid4()), "content": prompt},
            )
            if not isinstance(submission, dict):
                raise RuntimeError("message submission response is invalid")
            run = submission.get("run")
            if not isinstance(run, dict):
                raise RuntimeError("run response is invalid")
            await consume_until_terminal(base_url, credential, websocket, state, str(run["id"]))


def main() -> None:
    """CLI entry point; credentials never appear in arguments or output."""

    del sys.argv[1:]
    base_url = os.environ.get("BMO_CONVERSATION_API_URL", "http://127.0.0.1:8000")
    asyncio.run(interactive(base_url, read_credential()))


if __name__ == "__main__":
    main()
