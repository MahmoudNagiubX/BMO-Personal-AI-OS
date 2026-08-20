"""Loopback-only llama.cpp adapter for the measured optional advanced model."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from personal_ai_os.model_gateway.config import validate_local_endpoint
from personal_ai_os.model_gateway.contracts import (
    ProviderEmbeddingResult,
    ProviderGenerationRequest,
    ProviderGenerationResult,
    ProviderModel,
)
from personal_ai_os.model_gateway.provider import (
    ProviderContractError,
    ProviderOfflineError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderTransientError,
)


class LlamaCppProvider:
    """Call only the pinned local llama-server HTTP surface."""

    def __init__(
        self,
        endpoint: str,
        *,
        model_filename: str,
        model_sha256: str,
        expected_build: str,
        sleep_idle_seconds: int = 12,
    ) -> None:
        self._endpoint = validate_local_endpoint(endpoint)
        self._model_filename = self._validate_model_filename(model_filename)
        self._model_sha256 = self._validate_sha(model_sha256)
        self._expected_build = expected_build
        self._sleep_idle_seconds = sleep_idle_seconds

    def version(self, *, timeout_seconds: float) -> str:
        value = self._props(timeout_seconds).get("build_info")
        if not isinstance(value, str):
            raise ProviderContractError("llama.cpp build information is invalid")
        return value

    def inventory(self, *, timeout_seconds: float) -> tuple[ProviderModel, ...]:
        props = self._props(timeout_seconds)
        model_path = props.get("model_path")
        if not isinstance(model_path, str) or not model_path:
            raise ProviderContractError("llama.cpp model path is missing")
        remote_filename = model_path.replace("\\", "/").rsplit("/", 1)[-1]
        if remote_filename.casefold() != self._model_filename.casefold():
            raise ProviderContractError(
                "llama.cpp model filename does not match the pinned artifact"
            )
        return (
            ProviderModel(
                model_id="qwen3.5-heretic:9b-q4km",
                digest=f"sha256:{self._model_sha256}",
            ),
        )

    def generate(
        self,
        request: ProviderGenerationRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderGenerationResult:
        if request.images or request.structured_schema is not None or request.tools:
            raise ProviderRequestError("llama.cpp advanced provider is text-only")
        body = {
            "model": request.model_id,
            "messages": [
                {"role": message.role.value, "content": message.text}
                for message in request.messages
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": request.max_output_tokens,
            "reasoning_format": "none",
        }
        payload = self._request_json("POST", "/v1/chat/completions", body, timeout_seconds)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ProviderContractError("llama.cpp completion choices are invalid")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ProviderContractError("llama.cpp completion message is invalid")
        text = message.get("content", "")
        reasoning = message.get("reasoning_content", "")
        if not isinstance(text, str) or not isinstance(reasoning, str):
            raise ProviderContractError("llama.cpp completion content is invalid")
        if not text and reasoning:
            text = reasoning
        usage = payload.get("usage", {})
        if not isinstance(usage, Mapping):
            usage = {}
        return ProviderGenerationResult(
            text=text,
            finish_reason=self._string_or_default(choice.get("finish_reason"), "stop"),
            prompt_tokens=self._nonnegative_int(usage.get("prompt_tokens", 0)),
            output_tokens=self._nonnegative_int(usage.get("completion_tokens", 0)),
        )

    def embed(
        self,
        model_id: str,
        texts: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> ProviderEmbeddingResult:
        del model_id, texts, timeout_seconds
        raise ProviderRequestError("llama.cpp advanced provider does not provide embeddings")

    def ensure_awake(self, *, timeout_seconds: float) -> None:
        """Verify props without relying on health to wake a sleeping model."""

        self._props(timeout_seconds)

    def ensure_sleeping(self, *, timeout_seconds: float) -> bool:
        """Wait for idle unload and verify the server's explicit sleeping state."""

        props = self._props(timeout_seconds)
        if props.get("is_sleeping") is True:
            return True
        deadline = time.monotonic() + max(
            2.0, min(float(self._sleep_idle_seconds) + 2.0, timeout_seconds)
        )
        while time.monotonic() < deadline:
            try:
                if self._props(timeout_seconds).get("is_sleeping") is True:
                    return True
            except Exception:
                return False
            time.sleep(0.25)
        return False

    def _props(self, timeout_seconds: float) -> Mapping[str, Any]:
        payload = self._request_json("GET", "/props", None, timeout_seconds)
        build_info = payload.get("build_info")
        if not isinstance(build_info, str) or build_info != self._expected_build:
            raise ProviderContractError("llama.cpp build identity does not match the pin")
        modalities = payload.get("modalities")
        if isinstance(modalities, Mapping) and any(
            modalities.get(key) for key in ("vision", "video", "audio")
        ):
            raise ProviderContractError("advanced llama.cpp runtime unexpectedly exposes media")
        return payload

    def _request_json(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            f"{self._endpoint}{path}",
            data=encoded,
            headers={"Content-Type": "application/json"} if encoded is not None else {},
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in {408, 504}:
                raise ProviderTimeoutError("llama.cpp request timed out") from exc
            if exc.code == 429 or exc.code >= 500:
                raise ProviderTransientError("llama.cpp returned a transient status") from exc
            raise ProviderRequestError("llama.cpp rejected the bounded request") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("llama.cpp request timed out") from exc
        except (URLError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError("llama.cpp request timed out") from exc
            raise ProviderOfflineError("llama.cpp is unreachable") from exc
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderContractError("llama.cpp returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ProviderContractError("llama.cpp JSON root is invalid")
        return payload

    @staticmethod
    def _validate_sha(value: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in value)
        ):
            raise ValueError("llama_cpp_model_sha256 must be a SHA-256 hex digest")
        return value.lower()

    @staticmethod
    def _validate_model_filename(value: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(separator in value for separator in ("/", "\\"))
            or not value.casefold().endswith(".gguf")
        ):
            raise ValueError("model_filename must be a stable GGUF filename")
        return value

    @staticmethod
    def _nonnegative_int(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProviderContractError("llama.cpp usage is invalid")
        return value

    @staticmethod
    def _string_or_default(value: object, default: str) -> str:
        return value if isinstance(value, str) and value else default


__all__ = ["LlamaCppProvider"]
