from __future__ import annotations

import json
from urllib.request import Request

import pytest

from personal_ai_os.model_gateway import LlamaCppProvider
from personal_ai_os.model_gateway.contracts import Message, MessageRole, ProviderGenerationRequest
from personal_ai_os.model_gateway.provider import ProviderContractError


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


EXPECTED_SHA = "8d463c63e2c8759ad263cba59f1fa7a0be9a7cacb59b0fd0a787b7daa31597ad"
MODEL_PATH = "C:/synthetic/Qwen3.5-9B-ultra-uncensored-heretic-v2-Q4_K_M.gguf"


def props(*, sleeping: bool = False, path: str = MODEL_PATH) -> dict[str, object]:
    return {
        "build_info": "b10502-0adcc3bb5",
        "model_path": path,
        "model_ftype": "Q4_K - Medium",
        "modalities": {"vision": False, "video": False, "audio": False},
        "is_sleeping": sleeping,
    }


def provider_request() -> ProviderGenerationRequest:
    return ProviderGenerationRequest(
        model_id="qwen3.5-heretic:9b-q4km",
        messages=(Message(MessageRole.USER, "Synthetic advanced request"),),
        images=(),
        context_tokens=4096,
        max_output_tokens=32,
        structured_schema=None,
        tools=(),
    )


def test_llama_cpp_provider_attests_props_and_normalizes_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []
    generation_done = False

    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        del timeout
        nonlocal generation_done
        requests.append(request)
        if request.full_url.endswith("/props"):
            current = props(sleeping=generation_done)
            generation_done = True
            return FakeResponse(current)
        response = FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "advanced response"},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            }
        )
        generation_done = True
        return response

    monkeypatch.setattr("personal_ai_os.model_gateway.llama_cpp.urlopen", fake_urlopen)
    provider = LlamaCppProvider(
        "http://127.0.0.1:11435",
        model_path=MODEL_PATH,
        model_sha256=EXPECTED_SHA,
        expected_build="b10502-0adcc3bb5",
        sleep_idle_seconds=2,
    )
    assert provider.version(timeout_seconds=2) == "b10502-0adcc3bb5"
    assert provider.inventory(timeout_seconds=2)[0].digest == f"sha256:{EXPECTED_SHA}"
    result = provider.generate(provider_request(), timeout_seconds=10)
    assert result.text == "advanced response"
    assert result.output_tokens == 3
    assert provider.ensure_sleeping(timeout_seconds=2) is True
    assert any(request.full_url.endswith("/v1/chat/completions") for request in requests)
    assert not any(request.full_url.endswith("/api/generate") for request in requests)


def test_llama_cpp_provider_rejects_wrong_path_and_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Request, *, timeout: float) -> FakeResponse:
        del request, timeout
        return FakeResponse(props(path="C:/synthetic/wrong.gguf"))

    monkeypatch.setattr("personal_ai_os.model_gateway.llama_cpp.urlopen", fake_urlopen)
    provider = LlamaCppProvider(
        "http://127.0.0.1:11435",
        model_path=MODEL_PATH,
        model_sha256=EXPECTED_SHA,
        expected_build="b10502-0adcc3bb5",
    )
    with pytest.raises(ProviderContractError):
        provider.inventory(timeout_seconds=2)


@pytest.mark.parametrize("endpoint", ["http://192.168.1.10:11435", "https://127.0.0.1:11435"])
def test_llama_cpp_provider_is_loopback_only(endpoint: str) -> None:
    with pytest.raises(ValueError):
        LlamaCppProvider(
            endpoint,
            model_path=MODEL_PATH,
            model_sha256=EXPECTED_SHA,
            expected_build="b10502-0adcc3bb5",
        )
