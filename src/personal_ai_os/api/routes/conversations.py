"""Authenticated REST and WebSocket text-conversation boundaries."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
)
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from personal_ai_os.api.identity_dependencies import (
    get_database_session,
    require_device_scopes,
)
from personal_ai_os.conversations.contracts import (
    CancelResponse,
    ConversationCreateRequest,
    ConversationResponse,
    ConversationSessionCreateRequest,
    ConversationSessionResponse,
    MessageResponse,
    MessageSubmitRequest,
    RunResponse,
    SubmitMessageResponse,
)
from personal_ai_os.conversations.errors import (
    AgentRunNotFoundError,
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationSessionNotFoundError,
    IdempotencyConflictError,
    SessionClosedError,
)
from personal_ai_os.conversations.reconciliation import sync_application_gate_state
from personal_ai_os.conversations.service import ConversationService
from personal_ai_os.core.correlation import get_correlation_id
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.identity.errors import AuthenticationError, ScopeDeniedError
from personal_ai_os.identity.service import IdentityService

router = APIRouter(prefix="/api/v1", tags=["conversations"])
WEBSOCKET_REVALIDATION_SECONDS = 2.0
ReadPrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("conversation.read"))]
WritePrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("conversation.write"))]
CancelPrincipal = Annotated[
    DevicePrincipal,
    Depends(require_device_scopes("conversation.read", "conversation.run.cancel")),
]


def get_service(
    request: Request,
    session: Annotated[Session, Depends(get_database_session)],
) -> ConversationService:
    """Construct a request-scoped conversation service."""

    gate = request.app.state.conversation_reconciliation_gate
    if not gate.ensure_ready(request.app.state.database_session_factory):
        sync_application_gate_state(request.app, gate)
        raise HTTPException(status_code=503, detail="conversation service unavailable")
    sync_application_gate_state(request.app, gate)
    return ConversationService(session)


ServiceDependency = Annotated[ConversationService, Depends(get_service)]


def _not_found(_: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail="conversation resource is not available")


def _conflict(error: Exception) -> HTTPException:
    if isinstance(error, ConversationBusyError):
        return HTTPException(status_code=409, detail="conversation_busy")
    if isinstance(error, IdempotencyConflictError):
        return HTTPException(status_code=409, detail="idempotency_conflict")
    if isinstance(error, SessionClosedError):
        return HTTPException(status_code=409, detail="session_closed")
    return HTTPException(status_code=409, detail="conversation_conflict")


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    request: ConversationCreateRequest,
    principal: WritePrincipal,
    service: ServiceDependency,
) -> ConversationResponse:
    """Create a durable owner-scoped conversation."""

    return service.to_conversation_response(service.create_conversation(principal, request.title))


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    principal: ReadPrincipal,
    service: ServiceDependency,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> list[ConversationResponse]:
    """List bounded owner-scoped conversations."""

    return [
        service.to_conversation_response(row)
        for row in service.list_conversations(principal, limit=limit, offset=offset)
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    principal: ReadPrincipal,
    service: ServiceDependency,
) -> ConversationResponse:
    """Read one owner-scoped conversation."""

    try:
        return service.to_conversation_response(
            service.get_conversation(principal, conversation_id)
        )
    except ConversationNotFoundError as error:
        raise _not_found(error) from error


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(
    conversation_id: UUID,
    principal: ReadPrincipal,
    service: ServiceDependency,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[MessageResponse]:
    """Read bounded canonical conversation messages."""

    try:
        return [
            service.to_message_response(row)
            for row in service.get_messages(principal, conversation_id, limit=limit)
        ]
    except ConversationNotFoundError as error:
        raise _not_found(error) from error


@router.post(
    "/conversations/{conversation_id}/sessions",
    response_model=ConversationSessionResponse,
    status_code=201,
)
def create_session(
    conversation_id: UUID,
    request: ConversationSessionCreateRequest,
    principal: WritePrincipal,
    service: ServiceDependency,
) -> ConversationSessionResponse:
    """Open a new session bound to the authenticated device."""

    del request
    try:
        return service.to_session_response(service.create_session(principal, conversation_id))
    except ConversationNotFoundError as error:
        raise _not_found(error) from error


@router.get("/conversation-sessions/{session_id}", response_model=ConversationSessionResponse)
def get_session(
    session_id: UUID,
    principal: ReadPrincipal,
    service: ServiceDependency,
) -> ConversationSessionResponse:
    """Read a device-bound session."""

    try:
        return service.to_session_response(service.get_session(principal, session_id))
    except ConversationSessionNotFoundError as error:
        raise _not_found(error) from error


@router.post(
    "/conversation-sessions/{session_id}/close", response_model=ConversationSessionResponse
)
def close_session(
    session_id: UUID,
    principal: WritePrincipal,
    service: ServiceDependency,
) -> ConversationSessionResponse:
    """Close a session without deleting its history."""

    try:
        return service.to_session_response(service.close_session(principal, session_id))
    except ConversationSessionNotFoundError as error:
        raise _not_found(error) from error


@router.post("/conversation-sessions/{session_id}/messages", response_model=SubmitMessageResponse)
def submit_message(
    session_id: UUID,
    request: MessageSubmitRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    principal: WritePrincipal,
    service: ServiceDependency,
    http_request: Request,
) -> SubmitMessageResponse:
    """Persist one idempotent user message and enqueue a bounded run."""

    try:
        submission = service.submit_message(
            principal,
            session_id,
            request.client_message_id,
            request.content,
            correlation_id=get_correlation_id(),
            requested_model=request.model,
        )
    except (ConversationBusyError, IdempotencyConflictError, SessionClosedError) as error:
        raise _conflict(error) from error
    except (ConversationSessionNotFoundError, ConversationNotFoundError) as error:
        raise _not_found(error) from error
    if not submission.replayed:
        http_request.app.state.conversation_executor.submit(submission.run.id)
        response.status_code = 202
    else:
        response.status_code = 200
    return SubmitMessageResponse(
        message=service.to_message_response(submission.message),
        run=service.to_run_response(submission.run),
        replayed=submission.replayed,
    )


@router.get("/conversations/{conversation_id}/runs", response_model=list[RunResponse])
def list_runs(
    conversation_id: UUID,
    principal: ReadPrincipal,
    service: ServiceDependency,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[RunResponse]:
    """Read bounded factual run history."""

    try:
        return [
            service.to_run_response(row)
            for row in service.get_runs(principal, conversation_id, limit=limit)
        ]
    except ConversationNotFoundError as error:
        raise _not_found(error) from error


@router.get("/agent-runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: UUID,
    principal: ReadPrincipal,
    service: ServiceDependency,
) -> RunResponse:
    """Read one owner-scoped run."""

    try:
        return service.to_run_response(service.get_run(principal, run_id))
    except AgentRunNotFoundError as error:
        raise _not_found(error) from error


@router.post("/agent-runs/{run_id}/cancel", response_model=CancelResponse)
def cancel_run(
    run_id: UUID,
    principal: CancelPrincipal,
    service: ServiceDependency,
) -> CancelResponse:
    """Request cancellation with truthful queued/running semantics."""

    try:
        return CancelResponse(run=service.to_run_response(service.cancel_run(principal, run_id)))
    except AgentRunNotFoundError as error:
        raise _not_found(error) from error


def _websocket_credential(websocket: WebSocket) -> str | None:
    value = websocket.headers.get("authorization")
    if value is None:
        return None
    scheme, _, credential = value.partition(" ")
    if scheme.casefold() != "bearer" or not credential or " " in credential:
        return None
    return credential


async def _close_unauthenticated(websocket: WebSocket) -> None:
    await websocket.close(code=4401, reason="unauthenticated")


async def _observe_disconnect(websocket: WebSocket) -> None:
    """Observe ASGI disconnects while the server is polling for new events."""

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            # Client frames are not conversation commands and are deliberately ignored.
    except (RuntimeError, WebSocketDisconnect):
        return


def _websocket_principal(
    factory: sessionmaker[Session], principal: DevicePrincipal, session_id: UUID
) -> DevicePrincipal:
    """Revalidate current identity, scopes, and active-session ownership."""

    with factory() as session:
        identity = IdentityService(session)
        refreshed = identity.revalidate_principal(principal)
        identity.require_scopes(refreshed, "conversation.read", "conversation.stream")
        conversation_session = ConversationService(session).get_session(refreshed, session_id)
        if conversation_session.status != "active":
            raise SessionClosedError("conversation session is closed")
    return refreshed


@router.websocket("/conversation-sessions/{session_id}/events")
async def conversation_events(
    websocket: WebSocket,
    session_id: UUID,
    after_sequence: int = Query(default=0, ge=0, le=10_000_000),
) -> None:
    """Stream persisted lifecycle events with bounded polling and replay."""

    raw_credential = _websocket_credential(websocket)
    if raw_credential is None:
        await _close_unauthenticated(websocket)
        return
    gate = websocket.app.state.conversation_reconciliation_gate
    if not gate.ensure_ready(websocket.app.state.database_session_factory):
        sync_application_gate_state(websocket.app, gate)
        await websocket.close(code=1013, reason="conversation service unavailable")
        return
    sync_application_gate_state(websocket.app, gate)
    factory = websocket.app.state.database_session_factory
    try:
        with factory() as session:
            identity = IdentityService(session)
            principal = identity.authenticate(raw_credential)
            identity.require_scopes(principal, "conversation.read", "conversation.stream")
            conversation_session = ConversationService(session).get_session(principal, session_id)
            if conversation_session.status != "active":
                raise SessionClosedError("conversation session is closed")
    except AuthenticationError:
        await _close_unauthenticated(websocket)
        return
    except (ScopeDeniedError, ConversationSessionNotFoundError, SessionClosedError):
        await websocket.close(code=4403, reason="unauthorized")
        return
    await websocket.accept()
    sequence = after_sequence
    last_revalidated = asyncio.get_running_loop().time()
    disconnect_task = asyncio.create_task(_observe_disconnect(websocket))
    try:
        while True:
            if disconnect_task.done():
                return
            now = asyncio.get_running_loop().time()
            if now - last_revalidated >= WEBSOCKET_REVALIDATION_SECONDS:
                try:
                    principal = _websocket_principal(factory, principal, session_id)
                except AuthenticationError:
                    await websocket.close(code=4401, reason="unauthenticated")
                    return
                except (ScopeDeniedError, ConversationSessionNotFoundError, SessionClosedError):
                    await websocket.close(code=4403, reason="unauthorized")
                    return
                except Exception:
                    await websocket.close(code=1013, reason="conversation service unavailable")
                    return
                last_revalidated = now
            with factory() as session:
                events = ConversationService(session).replay_events(principal, session_id, sequence)
            if events:
                # Revalidate immediately before protected event delivery.
                try:
                    principal = _websocket_principal(factory, principal, session_id)
                except AuthenticationError:
                    await websocket.close(code=4401, reason="unauthenticated")
                    return
                except (ScopeDeniedError, ConversationSessionNotFoundError, SessionClosedError):
                    await websocket.close(code=4403, reason="unauthorized")
                    return
                except Exception:
                    await websocket.close(code=1013, reason="conversation service unavailable")
                    return
                last_revalidated = asyncio.get_running_loop().time()
                if disconnect_task.done():
                    return
                for event in events:
                    await websocket.send_json(event.model_dump(mode="json"))
                sequence = events[-1].sequence
            else:
                try:
                    await asyncio.wait_for(asyncio.shield(disconnect_task), timeout=0.25)
                    return
                except TimeoutError:
                    pass
    except WebSocketDisconnect:
        return
    finally:
        if not disconnect_task.done():
            disconnect_task.cancel()
        await asyncio.gather(disconnect_task, return_exceptions=True)


__all__ = ["router"]
