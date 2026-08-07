from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from personal_ai_os.model_gateway import ImageInput, Message, MessageRole, OllamaProvider
from personal_ai_os.model_gateway.contracts import ProviderGenerationRequest, ToolDefinition
from personal_ai_os.model_gateway.provider import (
    ProviderOfflineError,
    ProviderRequestError,
    ProviderTransientError,
)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def provider_request(**changes: object) -> ProviderGenerationRequest:
    values: dict[str, object] = {
        "model_id": "qwen3.5:4b",
        "messages": (Message(MessageRole.USER, "Synthetic prompt"),),
        "images": (),
        "context_tokens": 4096,
        "max_output_tokens": 32,
        "structured_schema": None,
        "tools": (),
    }
    values.update(changes)
    return ProviderGenerationRequest(**values)  # type: ignore[arg-type]


def test_adapter_calls_only_fixed_local_version_and_inventory_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []

    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout == 2.0
        requests.append(request)
        if request.full_url.endswith("/api/version"):
            return FakeResponse({"version": "0.32.5"})
        return FakeResponse(
            {
                "models": [
                    {"name": "qwen3.5:4b", "digest": "a" * 64},
                    {"name": "bge-m3:567m", "digest": "sha256:" + "b" * 64},
                ]
            }
        )

    monkeypatch.setattr("personal_ai_os.model_gateway.ollama.urlopen", fake_urlopen)
    provider = OllamaProvider("http://127.0.0.1:11434")
    assert provider.version(timeout_seconds=2.0) == "0.32.5"
    assert [model.model_id for model in provider.inventory(timeout_seconds=2.0)] == [
        "qwen3.5:4b",
        "bge-m3:567m",
    ]
    assert [model.digest for model in provider.inventory(timeout_seconds=2.0)] == [
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
    ]
    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:11434/api/version",
        "http://127.0.0.1:11434/api/tags",
        "http://127.0.0.1:11434/api/tags",
    ]
    assert all(request.get_header("Authorization") is None for request in requests)


def test_adapter_translates_generation_without_exposing_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert timeout == 10.0
        captured.append(json.loads(request.data or b"{}"))
        return FakeResponse(
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "set_scene", "arguments": {"name": "focus"}}}
                    ],
                },
                "done_reason": "stop",
                "prompt_eval_count": 4,
                "eval_count": 2,
            }
        )

    monkeypatch.setattr("personal_ai_os.model_gateway.ollama.urlopen", fake_urlopen)
    tool = ToolDefinition(
        name="set_scene",
        description="Synthetic proposal.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )
    image = ImageInput("image/png", b"synthetic-image")
    result = OllamaProvider("http://127.0.0.1:11434").generate(
        provider_request(images=(image,), tools=(tool,)), timeout_seconds=10.0
    )
    assert result.tool_calls[0].name == "set_scene"
    assert result.prompt_tokens == 4
    assert captured[0]["model"] == "qwen3.5:4b"
    assert captured[0]["stream"] is False
    assert captured[0]["think"] is False
    assert captured[0]["keep_alive"] == 0
    assert "images" in captured[0]["messages"][0]  # type: ignore[index]
    assert "synthetic-image" not in json.dumps(captured[0])


def test_adapter_translates_embedding_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        assert request.full_url.endswith("/api/embed")
        assert timeout == 5.0
        return FakeResponse({"embeddings": [[0.0, 1.0], [1.0, 0.0]]})

    monkeypatch.setattr("personal_ai_os.model_gateway.ollama.urlopen", fake_urlopen)
    result = OllamaProvider("http://127.0.0.1:11434").embed(
        "bge-m3:567m", ("one", "two"), timeout_seconds=5.0
    )
    assert result.vectors == ((0.0, 1.0), (1.0, 0.0))


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (URLError("raw private transport"), ProviderOfflineError),
        (
            HTTPError(
                "http://127.0.0.1:11434/api/version",
                500,
                "raw private provider error",
                {},
                BytesIO(b"raw private body"),
            ),
            ProviderTransientError,
        ),
        (
            HTTPError(
                "http://127.0.0.1:11434/api/version",
                400,
                "raw private provider error",
                {},
                BytesIO(b"raw private body"),
            ),
            ProviderRequestError,
        ),
    ],
)
def test_adapter_normalizes_transport_failures_without_raw_payload(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected: type[Exception],
) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        del request, timeout
        raise failure

    monkeypatch.setattr("personal_ai_os.model_gateway.ollama.urlopen", fake_urlopen)
    with pytest.raises(expected) as exc_info:
        OllamaProvider("http://127.0.0.1:11434").version(timeout_seconds=1.0)
    assert "raw private" not in str(exc_info.value)
