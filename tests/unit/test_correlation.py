from __future__ import annotations

from contextlib import suppress

from fastapi import FastAPI
from fastapi.testclient import TestClient

from personal_ai_os.core.correlation import (
    CorrelationIdMiddleware,
    get_correlation_id,
    normalize_correlation_id,
)


def _context_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/context")
    def context() -> dict[str, str | None]:
        return {"correlation_id": get_correlation_id()}

    return app


def test_invalid_supplied_id_is_replaced() -> None:
    generated = normalize_correlation_id("contains spaces")

    assert generated != "contains spaces"
    assert len(generated) == 36


def test_context_is_reset_after_each_request() -> None:
    with TestClient(_context_app()) as client:
        first = client.get("/context", headers={"X-Correlation-ID": "first"})
        second = client.get("/context", headers={"X-Correlation-ID": "second"})

    assert first.json() == {"correlation_id": "first"}
    assert second.json() == {"correlation_id": "second"}
    assert get_correlation_id() is None


def test_context_is_reset_when_application_raises() -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/error")
    def error() -> None:
        raise RuntimeError("synthetic failure")

    with TestClient(app, raise_server_exceptions=True) as client, suppress(RuntimeError):
        client.get("/error", headers={"X-Correlation-ID": "error-case"})

    assert get_correlation_id() is None
