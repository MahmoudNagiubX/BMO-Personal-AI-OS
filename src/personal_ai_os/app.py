"""FastAPI application factory for the Phase 2 platform skeleton."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from personal_ai_os.api.router import api_router
from personal_ai_os.core.config import get_settings
from personal_ai_os.core.correlation import CorrelationIdMiddleware
from personal_ai_os.core.logging import configure_logging
from personal_ai_os.db.engine import create_engine_for_settings, create_session_factory
from personal_ai_os.db.health import create_database_health_check


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Dispose the lazy database engine when the application shuts down."""

    yield
    app.state.database_engine.dispose()


def create_app() -> FastAPI:
    """Create a configured application without opening a database connection."""

    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    database_engine = create_engine_for_settings(settings)
    app.state.database_engine = database_engine
    app.state.database_session_factory = create_session_factory(database_engine)
    app.state.database_health = create_database_health_check(database_engine)

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        """Reject invalid boundary data without echoing untrusted secret-like inputs."""

        return JSONResponse(status_code=422, content={"detail": "invalid request"})

    app.include_router(api_router)
    app.add_middleware(CorrelationIdMiddleware)
    return app
