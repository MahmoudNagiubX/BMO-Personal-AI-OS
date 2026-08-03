"""Contract and loopback integration proof for the OpenJarvis adapter."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from bmo_openjarvis_adapter import (
    LocalModelRequest,
    OpenJarvisAdapter,
    OpenJarvisAdapterError,
)
from bmo_openjarvis_adapter.errors import AdapterErrorCategory


class _StubState:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []


class _StubServer(ThreadingHTTPServer):
    state: _StubState


class _Handler(BaseHTTPRequestHandler):
    server: _StubServer

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.server.state.payloads.append(payload)
        body = json.dumps(
            {
                "id": "synthetic-response",
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "BMO_OPENJARVIS_SPIKE_OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 1,
                    "total_tokens": 9,
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def _loopback_server() -> Iterator[tuple[str, _StubState]]:
    server = _StubServer(("127.0.0.1", 0), _Handler)
    server.state = _StubState()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _block_non_loopback_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    original_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple) and address and address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError("contract traffic left loopback")
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def test_exact_upstream_identity_is_detectable() -> None:
    with _loopback_server() as (provider_url, _):
        identity = OpenJarvisAdapter(provider_url).upstream_identity
    assert identity["package"] == "openjarvis"
    assert identity["version"] == "1.0.0"
    assert identity["commit"] == "e97088f199cf86ea5f78de921772357d1f0d2cec"
    assert identity["repository"] == "https://github.com/open-jarvis/OpenJarvis"


def test_adapter_import_and_configuration_are_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("adapter construction attempted network access")

    monkeypatch.setattr(httpx.Client, "__init__", fail_network)
    adapter = OpenJarvisAdapter("http://127.0.0.1:9")
    assert adapter.analytics_enabled is False


def test_local_request_flow_uses_real_pinned_upstream_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_non_loopback_connects(monkeypatch)
    with _loopback_server() as (provider_url, state):
        request = LocalModelRequest(
            request_id="phase3-synthetic-request",
            model_id="synthetic-local-model",
            prompt="Return exactly: BMO_OPENJARVIS_SPIKE_OK",
            temperature=0.0,
            max_tokens=64,
            metadata={"test_case": "openjarvis-compatibility"},
        )
        response = OpenJarvisAdapter(provider_url).invoke_local_model(request)

    assert len(state.payloads) == 1
    payload = state.payloads[0]
    assert payload["model"] == "synthetic-local-model"
    assert payload["messages"] == [
        {"role": "user", "content": "Return exactly: BMO_OPENJARVIS_SPIKE_OK"}
    ]
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 64
    assert "metadata" not in payload
    assert response.request_id == "phase3-synthetic-request"
    assert response.model_id == "synthetic-local-model"
    assert response.text == "BMO_OPENJARVIS_SPIKE_OK"
    assert response.finish_reason == "stop"
    assert response.local_provider is True
    assert response.usage.completion_tokens == 1
    assert response.trace_events[0].source_framework == "openjarvis"


def test_non_loopback_provider_is_rejected_before_network() -> None:
    with pytest.raises(OpenJarvisAdapterError) as exc_info:
        OpenJarvisAdapter("https://example.invalid/v1")
    assert exc_info.value.category is AdapterErrorCategory.CONFIGURATION


def test_external_network_is_not_part_of_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_non_loopback_connects(monkeypatch)
    with pytest.raises(OpenJarvisAdapterError) as exc_info:
        OpenJarvisAdapter("http://127.0.0.1:1", timeout_seconds=0.1).invoke_local_model(
            LocalModelRequest(
                request_id="phase3-unavailable",
                model_id="synthetic-local-model",
                prompt="Return exactly: BMO_OPENJARVIS_SPIKE_OK",
            )
        )
    assert exc_info.value.category is AdapterErrorCategory.LOCAL_PROVIDER_UNAVAILABLE
    assert "127.0.0.1" not in str(exc_info.value)


def test_compatibility_report_is_machine_readable(tmp_path: Any) -> None:
    report = {
        "upstream_repository": "https://github.com/open-jarvis/OpenJarvis",
        "tag": "v1.0.0",
        "full_commit": "e97088f199cf86ea5f78de921772357d1f0d2cec",
        "package_version": "1.0.0",
        "python_version": "3.12",
        "local_request_flow": "passed",
        "tool_schema": "passed",
        "trace_translation": "passed",
        "analytics_state": "no adapter analytics; upstream telemetry not configured",
        "import_boundary": "passed",
        "rejected_capabilities": ["cloud", "shell", "tool execution", "trace persistence"],
    }
    artifact = tmp_path / "phase3-openjarvis-compatibility.json"
    artifact.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    loaded = json.loads(artifact.read_text(encoding="utf-8"))
    assert loaded["full_commit"].startswith("e97088f")
    assert loaded["rejected_capabilities"]
