"""FastAPI application factory for the Phase 2 platform skeleton."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from personal_ai_os.api.router import api_router
from personal_ai_os.conversations.executor import ConversationExecutor
from personal_ai_os.conversations.reconciliation import (
    ConversationReconciliationGate,
    sync_application_gate_state,
)
from personal_ai_os.core.config import get_settings
from personal_ai_os.core.correlation import CorrelationIdMiddleware
from personal_ai_os.core.logging import configure_logging
from personal_ai_os.db.engine import create_engine_for_settings, create_session_factory
from personal_ai_os.db.health import create_database_health_check
from personal_ai_os.model_gateway import (
    GatewaySettings,
    LlamaCppProvider,
    ModelGateway,
    OllamaProvider,
)
from personal_ai_os.model_gateway.contracts import Provider
from personal_ai_os.model_gateway.provider import ModelProvider
from personal_ai_os.tools.reconciliation import ToolReconciliationGate, sync_tool_gate_state


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Reconcile interrupted runs, stale tool calls, and dispose bounded runtime resources."""

    gate: ConversationReconciliationGate = app.state.conversation_reconciliation_gate
    gate.attempt(app.state.database_session_factory)
    sync_application_gate_state(app, gate)

    tool_gate: ToolReconciliationGate = app.state.tool_reconciliation_gate
    tool_gate.attempt(app.state.database_session_factory)
    sync_tool_gate_state(app, tool_gate)
    try:
        yield
    finally:
        app.state.conversation_executor.shutdown()
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
    app.state.conversation_reconciliation_gate = ConversationReconciliationGate()
    app.state.conversation_reconciliation_ready = False
    app.state.conversation_reconciliation_deferred = False
    app.state.tool_reconciliation_gate = ToolReconciliationGate()
    app.state.tool_reconciliation_ready = False
    app.state.tool_reconciliation_deferred = False
    app.state.database_health = create_database_health_check(database_engine)
    gateway_settings = GatewaySettings()
    providers: dict[Provider, ModelProvider] = {
        Provider.OLLAMA: OllamaProvider(
            gateway_settings.ollama_endpoint,
            allow_private_network_endpoint=gateway_settings.allow_private_network_endpoint,
        )
    }
    if gateway_settings.llama_cpp_enabled:
        providers[Provider.LLAMA_CPP] = LlamaCppProvider(
            gateway_settings.llama_cpp_endpoint,
            model_filename=gateway_settings.llama_cpp_model_filename,
            model_sha256=gateway_settings.llama_cpp_model_sha256,
            expected_build=gateway_settings.expected_llama_cpp_build,
            sleep_idle_seconds=gateway_settings.llama_cpp_sleep_idle_seconds,
        )
    app.state.model_gateway = ModelGateway(providers, gateway_settings)
    app.state.conversation_executor = ConversationExecutor(
        app.state.database_session_factory,
        lambda: app.state.model_gateway,
    )

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        """Reject invalid boundary data without echoing untrusted secret-like inputs."""

        return JSONResponse(status_code=422, content={"detail": "invalid request"})

    app.include_router(api_router)
    app.add_middleware(CorrelationIdMiddleware)
    return app
