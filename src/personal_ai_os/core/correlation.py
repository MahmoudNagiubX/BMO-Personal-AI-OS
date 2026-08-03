"""Correlation-ID context and request middleware."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
correlation_id_context: ContextVar[str | None] = ContextVar(
    "bmo_correlation_id",
    default=None,
)
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def get_correlation_id() -> str | None:
    """Return the correlation ID for the current execution context."""

    return correlation_id_context.get()


def normalize_correlation_id(value: str | None) -> str:
    """Keep only bounded, header-safe caller IDs and generate the rest."""

    if value is not None and _SAFE_CORRELATION_ID.fullmatch(value):
        return value
    return str(uuid4())


def _request_correlation_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-correlation-id":
            if not isinstance(value, bytes):
                return None
            try:
                return value.decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


class CorrelationIdMiddleware:
    """Pure ASGI middleware that propagates and resets request correlation IDs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = normalize_correlation_id(_request_correlation_id(scope))
        token = correlation_id_context.set(correlation_id)
        started = perf_counter()
        status_code = 500

        async def send_with_correlation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            logger.info(
                "request completed",
                extra={
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
            correlation_id_context.reset(token)
