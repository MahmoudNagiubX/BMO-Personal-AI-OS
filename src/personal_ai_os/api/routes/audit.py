"""Bounded owner-scoped redacted audit read API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from personal_ai_os.api.identity_dependencies import get_database_session, require_device_scopes
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.tools.contracts import AuditResponse
from personal_ai_os.tools.service import ToolPlatformService

router = APIRouter(prefix="/api/v1", tags=["audit"])
AuditPrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("audit.read"))]
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("/audit", response_model=list[AuditResponse])
def list_audit(
    principal: AuditPrincipal,
    session: SessionDependency,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[AuditResponse]:
    return ToolPlatformService(session).audit(principal, limit=limit)
