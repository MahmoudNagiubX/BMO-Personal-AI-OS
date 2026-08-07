"""Narrow standard-library Ollama adapter for the Phase 5A gateway."""

from __future__ import annotations

import base64
import json
import re
import socket
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from personal_ai_os.model_gateway.config import validate_ollama_endpoint
from personal_ai_os.model_gateway.contracts import (
    ProviderEmbeddingResult,
    ProviderGenerationRequest,
    ProviderGenerationResult,
    ProviderModel,
    ProviderToolCall,
)
from personal_ai_os.model_gateway.provider import (
    ProviderContractError,
    ProviderOfflineError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderTransientError,
)

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class OllamaProvider:
    """Call only Ollama version, inventory, chat, and embedding endpoints."""

    def __init__(
        self,
        endpoint: str,
        *,
        allow_private_network_endpoint: bool = False,
    ) -> None:
        self._endpoint = validate_ollama_endpoint(
            endpoint,
            allow_private_network=allow_private_network_endpoint,
        )

    def version(self, *, timeout_seconds: float) -> str:
        payload = self._request_json("GET", "/api/version", None, timeout_seconds)
        version = payload.get("version")
        if not isinstance(version, str) or not version:
            raise ProviderContractError("provider version response is invalid")
        return version

    def inventory(self, *, timeout_seconds: float) -> tuple[ProviderModel, ...]:
        payload = self._request_json("GET", "/api/tags", None, timeout_seconds)
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ProviderContractError("provider inventory response is invalid")
        models: list[ProviderModel] = []
        for raw in raw_models:
            if not isinstance(raw, Mapping):
                raise ProviderContractError("provider inventory entry is invalid")
            model_id = raw.get("name", raw.get("model"))
            digest = raw.get("digest")
            if not isinstance(model_id, str) or not isinstance(digest, str):
                raise ProviderContractError("provider inventory identity is invalid")
            models.append(ProviderModel(model_id=model_id, digest=self._normalize_digest(digest)))
        return tuple(models)

    def generate(
        self,
        request: ProviderGenerationRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderGenerationResult:
        messages: list[dict[str, Any]] = [
            {"role": message.role.value, "content": message.text} for message in request.messages
        ]
        if request.images:
            target = next(
                (message for message in reversed(messages) if message["role"] == "user"),
                None,
            )
            if target is None:
                raise ProviderRequestError("vision request has no user message")
            target["images"] = [
                base64.b64encode(image.data).decode("ascii") for image in request.images
            ]
        body: dict[str, Any] = {
            "model": request.model_id,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": 0,
            "options": {
                "temperature": 0,
                "num_ctx": request.context_tokens,
                "num_predict": request.max_output_tokens,
            },
        }
        if request.structured_schema is not None:
            body["format"] = dict(request.structured_schema)
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.input_schema),
                    },
                }
                for tool in request.tools
            ]
        payload = self._request_json("POST", "/api/chat", body, timeout_seconds)
        message = payload.get("message")
        if not isinstance(message, Mapping):
            raise ProviderContractError("provider generation message is invalid")
        text = message.get("content", "")
        if not isinstance(text, str):
            raise ProviderContractError("provider generation content is invalid")
        tool_calls = self._tool_calls(message.get("tool_calls", []))
        return ProviderGenerationResult(
            text=text,
            finish_reason=self._optional_string(payload.get("done_reason")),
            prompt_tokens=self._nonnegative_int(payload.get("prompt_eval_count", 0)),
            output_tokens=self._nonnegative_int(payload.get("eval_count", 0)),
            tool_calls=tool_calls,
        )

    def embed(
        self,
        model_id: str,
        texts: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> ProviderEmbeddingResult:
        payload = self._request_json(
            "POST",
            "/api/embed",
            {"model": model_id, "input": list(texts), "truncate": False, "keep_alive": 0},
            timeout_seconds,
        )
        raw_vectors = payload.get("embeddings")
        if not isinstance(raw_vectors, list):
            raise ProviderContractError("provider embedding response is invalid")
        vectors: list[tuple[float, ...]] = []
        for raw_vector in raw_vectors:
            if not isinstance(raw_vector, list):
                raise ProviderContractError("provider embedding vector is invalid")
            values: list[float] = []
            for value in raw_vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ProviderContractError("provider embedding value is invalid")
                values.append(float(value))
            vectors.append(tuple(values))
        return ProviderEmbeddingResult(vectors=tuple(vectors))

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
                raise ProviderTimeoutError("local provider request timed out") from exc
            if exc.code == 429 or exc.code >= 500:
                raise ProviderTransientError("local provider returned a transient status") from exc
            raise ProviderRequestError("local provider rejected the request") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("local provider request timed out") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError("local provider request timed out") from exc
            raise ProviderOfflineError("local provider is unreachable") from exc
        except OSError as exc:
            raise ProviderOfflineError("local provider is unreachable") from exc
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderContractError("local provider returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ProviderContractError("local provider JSON root is invalid")
        return payload

    @staticmethod
    def _tool_calls(raw_calls: object) -> tuple[ProviderToolCall, ...]:
        if not isinstance(raw_calls, list):
            raise ProviderContractError("provider tool calls are invalid")
        calls: list[ProviderToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, Mapping):
                raise ProviderContractError("provider tool call is invalid")
            function = raw_call.get("function")
            if not isinstance(function, Mapping):
                raise ProviderContractError("provider tool function is invalid")
            name = function.get("name")
            arguments = function.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, Mapping):
                raise ProviderContractError("provider tool function data is invalid")
            calls.append(ProviderToolCall(name=name, arguments=dict(arguments)))
        return tuple(calls)

    @staticmethod
    def _nonnegative_int(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ProviderContractError("provider usage value is invalid")
        return value

    @staticmethod
    def _optional_string(value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ProviderContractError("provider finish reason is invalid")
        return value

    @staticmethod
    def _normalize_digest(value: str) -> str:
        raw_digest = value.removeprefix("sha256:")
        if not _SHA256.fullmatch(raw_digest):
            raise ProviderContractError("provider model digest is invalid")
        return f"sha256:{raw_digest.casefold()}"


__all__ = ["OllamaProvider"]
