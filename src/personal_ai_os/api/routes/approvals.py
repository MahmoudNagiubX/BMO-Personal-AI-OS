"""Owner-scoped approval queue and exact decision boundary."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from personal_ai_os.api.identity_dependencies import (
    get_database_session,
    get_tool_service,
    require_device_scopes,
)
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.tools.contracts import ApprovalDecisionRequest, ApprovalResponse
from personal_ai_os.tools.errors import ToolPlatformError
from personal_ai_os.tools.service import ToolPlatformService

router = APIRouter(prefix="/api/v1", tags=["approvals"])
ReadPrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("approval.read"))]
DecidePrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("approval.decide"))]
ToolServiceDependency = Annotated[ToolPlatformService, Depends(get_tool_service)]
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("/approvals", response_model=list[ApprovalResponse])
def list_approvals(
    principal: ReadPrincipal,
    service: ToolServiceDependency,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ApprovalResponse]:
    return service.approvals(principal, limit=limit)


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
def get_approval(
    approval_id: UUID,
    principal: ReadPrincipal,
    service: ToolServiceDependency,
) -> ApprovalResponse:
    try:
        return service.approval(principal, approval_id)
    except ToolPlatformError as error:
        raise HTTPException(status_code=404, detail="approval is not available") from error


def _decide(
    approval_id: UUID,
    approve: bool,
    principal: DevicePrincipal,
    service: ToolPlatformService,
) -> ApprovalResponse:
    try:
        return service.decide_approval(principal, approval_id, approve=approve)
    except ToolPlatformError as error:
        raise HTTPException(status_code=409, detail=error.code) from error


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
def decide_approval(
    approval_id: UUID,
    principal: DecidePrincipal,
    service: ToolServiceDependency,
) -> ApprovalResponse:
    return _decide(approval_id, True, principal, service)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
def reject_approval(
    approval_id: UUID,
    principal: DecidePrincipal,
    service: ToolServiceDependency,
) -> ApprovalResponse:
    return _decide(approval_id, False, principal, service)


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalResponse)
def decide_approval_legacy(
    approval_id: UUID,
    request: ApprovalDecisionRequest,
    principal: DecidePrincipal,
    service: ToolServiceDependency,
) -> ApprovalResponse:
    return _decide(approval_id, request.approve, principal, service)
