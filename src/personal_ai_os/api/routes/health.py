"""Health endpoint contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from personal_ai_os.core.config import Settings, get_settings

router = APIRouter()
DatabaseHealthCheck = Callable[[float], None]


class LivenessResponse(BaseModel):
    """Response for the process-only liveness check."""

    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    """Response for the database-backed readiness check."""

    status: Literal["ready"] = "ready"


def get_database_health(request: Request) -> DatabaseHealthCheck:
    """Resolve the app's replaceable database health function."""

    return cast(DatabaseHealthCheck, request.app.state.database_health)


@router.get("/health/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    """Report that the API process is running."""

    return LivenessResponse()


@router.get("/health/ready", response_model=ReadinessResponse)
def ready(
    settings: Annotated[Settings, Depends(get_settings)],
    health_check: Annotated[DatabaseHealthCheck, Depends(get_database_health)],
) -> ReadinessResponse:
    """Report readiness only when PostgreSQL answers a bounded health query."""

    try:
        health_check(settings.readiness_timeout_seconds)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from None
    return ReadinessResponse()
