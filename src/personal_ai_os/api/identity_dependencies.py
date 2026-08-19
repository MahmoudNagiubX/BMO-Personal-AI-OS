"""FastAPI dependencies for database sessions and device authentication."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from personal_ai_os.conversations.reconciliation import sync_application_gate_state
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.identity.errors import AuthenticationError, ScopeDeniedError
from personal_ai_os.identity.service import IdentityService

_bearer = HTTPBearer(auto_error=False)


def get_database_session(request: Request) -> Generator[Session, None, None]:
    """Yield one request-scoped SQLAlchemy session."""

    if (
        request.url.path.startswith("/api/v1/conversations")
        or request.url.path.startswith("/api/v1/conversation-sessions")
        or request.url.path.startswith("/api/v1/agent-runs")
    ):
        gate = request.app.state.conversation_reconciliation_gate
        if not gate.ensure_ready(request.app.state.database_session_factory):
            sync_application_gate_state(request.app, gate)
            raise HTTPException(status_code=503, detail="conversation service unavailable")
        sync_application_gate_state(request.app, gate)
    session = request.app.state.database_session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDependency = Annotated[Session, Depends(get_database_session)]


def get_identity_service(session: SessionDependency) -> IdentityService:
    """Construct the identity service around the request transaction boundary."""

    return IdentityService(session)


def authentication_failure() -> HTTPException:
    """Return one generic challenge for every credential authentication failure."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid device credential",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_device(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DevicePrincipal:
    """Authenticate an opaque bearer credential without identity-existence leaks."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise authentication_failure()
    try:
        return service.authenticate(credentials.credentials)
    except AuthenticationError as error:
        raise authentication_failure() from error


def require_device_scopes(*required: str) -> Callable[..., DevicePrincipal]:
    """Create a dependency that requires all named transport scopes."""

    def dependency(
        principal: Annotated[DevicePrincipal, Depends(authenticate_device)],
        service: Annotated[IdentityService, Depends(get_identity_service)],
    ) -> DevicePrincipal:
        try:
            service.require_scopes(principal, *required)
        except ScopeDeniedError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient scope",
            ) from error
        return principal

    return dependency
