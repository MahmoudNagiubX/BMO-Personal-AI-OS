"""Authenticated static Phase 8 tool catalog and request boundary."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from personal_ai_os.api.identity_dependencies import (
    get_database_session,
    get_tool_service,
    require_device_scopes,
)
from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.tools.contracts import (
    ToolCallRequest,
    ToolCallResponse,
    ToolCatalogItem,
)
from personal_ai_os.tools.errors import ToolConflictError, ToolPlatformError, ToolSchemaError
from personal_ai_os.tools.service import ToolPlatformService

router = APIRouter(prefix="/api/v1", tags=["tools"])
CatalogPrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("tool.catalog.read"))]
RequestPrincipal = Annotated[DevicePrincipal, Depends(require_device_scopes("tool.request"))]
ToolServiceDependency = Annotated[ToolPlatformService, Depends(get_tool_service)]
SessionDependency = Annotated[Session, Depends(get_database_session)]


@router.get("/tools", response_model=list[ToolCatalogItem])
def list_tools(
    principal: CatalogPrincipal, service: ToolServiceDependency
) -> list[ToolCatalogItem]:
    del principal
    return service.catalog()


@router.get("/tools/{name}", response_model=ToolCatalogItem)
def get_tool(
    name: str,
    principal: CatalogPrincipal,
    service: ToolServiceDependency,
    version: int = Query(default=1, ge=1, le=99),
) -> ToolCatalogItem:
    del principal
    try:
        descriptor = service.registry.resolve(name, version)
    except ToolPlatformError as error:
        raise HTTPException(status_code=404, detail="tool is not available") from error
    return ToolPlatformService._catalog_item(descriptor)


@router.post("/tool-calls", response_model=ToolCallResponse, status_code=status.HTTP_202_ACCEPTED)
def request_tool(
    request: ToolCallRequest,
    principal: RequestPrincipal,
    service: ToolServiceDependency,
) -> ToolCallResponse:
    try:
        return service.request_tool(principal, request)
    except ToolSchemaError as error:
        raise HTTPException(status_code=422, detail="tool input is invalid") from error
    except ToolConflictError as error:
        raise HTTPException(status_code=409, detail=error.code) from error
    except ToolPlatformError as error:
        raise HTTPException(status_code=403, detail=error.code) from error


@router.post("/tool-calls/{tool_call_id}/cancel", response_model=ToolCallResponse)
def cancel_tool(
    tool_call_id: UUID,
    principal: RequestPrincipal,
    service: ToolServiceDependency,
) -> ToolCallResponse:
    try:
        return service.cancel_tool_call(principal, tool_call_id)
    except ToolConflictError as error:
        raise HTTPException(status_code=409, detail=error.code) from error
    except ToolPlatformError as error:
        raise HTTPException(status_code=403, detail=error.code) from error
