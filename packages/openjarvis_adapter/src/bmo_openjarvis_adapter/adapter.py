"""Small product-owned OpenJarvis compatibility adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from bmo_openjarvis_adapter.contracts import (
    LocalModelRequest,
    LocalModelResponse,
    OpenJarvisToolSchema,
    ToolDefinition,
    Usage,
)
from bmo_openjarvis_adapter.errors import (
    AdapterErrorCategory,
    OpenJarvisAdapterError,
)
from bmo_openjarvis_adapter.trace import translate_trace
from bmo_openjarvis_adapter.upstream import generate, identity, translate_tool


class OpenJarvisAdapter:
    """Translate bounded product contracts to the pinned local OpenJarvis API."""

    def __init__(self, provider_url: str, *, timeout_seconds: float = 5.0) -> None:
        self._provider_url = _validate_provider_url(provider_url)
        if not 0.1 <= timeout_seconds <= 30.0:
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.CONFIGURATION,
                "timeout_seconds must be between 0.1 and 30.0",
            )
        self._timeout_seconds = timeout_seconds

    @property
    def upstream_identity(self) -> Mapping[str, str]:
        """Return verified package identity without contacting a provider."""
        return identity()

    @property
    def analytics_enabled(self) -> bool:
        """The adapter adds no analytics or external monitoring."""
        return False

    def invoke_local_model(self, request: LocalModelRequest) -> LocalModelResponse:
        """Invoke one loopback-only request and return product-owned data."""
        try:
            raw_response = generate(
                self._provider_url,
                request.prompt,
                model_id=request.model_id,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                timeout_seconds=self._timeout_seconds,
            )
        except OpenJarvisAdapterError:
            raise
        except Exception as exc:
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.LOCAL_PROVIDER_UNAVAILABLE,
                "the configured local provider did not complete the request",
            ) from exc

        usage = _usage(raw_response.get("usage"))
        raw_text = raw_response.get("content", "")
        if not isinstance(raw_text, str):
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.UPSTREAM_COMPATIBILITY,
                "OpenJarvis returned non-text response content",
            )
        finish_reason = raw_response.get("finish_reason", "")
        if not isinstance(finish_reason, str):
            finish_reason = ""
        try:
            trace_event = translate_trace(
                {
                    "request_id": request.request_id,
                    "model_id": request.model_id,
                    "finish_reason": finish_reason,
                    "usage": {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                    },
                    "provider": "loopback",
                    "local_provider": True,
                },
                trace_id=request.request_id,
            )
        except Exception as exc:
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.TRACE_TRANSLATION,
                "OpenJarvis trace data could not be translated",
            ) from exc
        return LocalModelResponse(
            request_id=request.request_id,
            model_id=request.model_id,
            text=raw_text,
            finish_reason=finish_reason,
            usage=usage,
            trace_events=(trace_event,),
            local_provider=True,
        )

    def translate_tool(self, tool: ToolDefinition) -> OpenJarvisToolSchema:
        """Translate declarative tool metadata without registering or executing it."""
        try:
            translated = translate_tool(tool)
        except (TypeError, ValueError) as exc:
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.INVALID_TOOL_SCHEMA,
                "the tool schema is not supported by the adapter contract",
            ) from exc
        except Exception as exc:
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.UPSTREAM_COMPATIBILITY,
                "OpenJarvis tool schema translation failed",
            ) from exc
        return OpenJarvisToolSchema(
            name=str(translated["name"]),
            description=str(translated["description"]),
            parameters=dict(translated["parameters"]),
        )


def _validate_provider_url(provider_url: str) -> str:
    try:
        parsed = urlsplit(provider_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise OpenJarvisAdapterError(
            AdapterErrorCategory.CONFIGURATION,
            "provider_url is not a valid loopback URL",
        ) from exc
    if (
        parsed.scheme != "http"
        or hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise OpenJarvisAdapterError(
            AdapterErrorCategory.CONFIGURATION,
            "provider_url must be an unauthenticated http://127.0.0.1:<port> URL",
        )
    return f"http://127.0.0.1:{port}"


def _usage(raw_usage: Any) -> Usage:
    if not isinstance(raw_usage, Mapping):
        return Usage()
    values: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = raw_usage.get(key, 0)
        values[key] = value if isinstance(value, int) and value >= 0 else 0
    total = values["total_tokens"] or values["prompt_tokens"] + values["completion_tokens"]
    return Usage(
        prompt_tokens=values["prompt_tokens"],
        completion_tokens=values["completion_tokens"],
        total_tokens=total,
    )


__all__ = ["OpenJarvisAdapter"]
