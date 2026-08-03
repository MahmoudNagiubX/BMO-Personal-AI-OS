"""Version endpoint contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from personal_ai_os import __version__
from personal_ai_os.core.config import Settings, get_settings

router = APIRouter()


class VersionResponse(BaseModel):
    """Public build identity without host or runtime details."""

    name: str
    version: str
    build_sha: str


@router.get("/version", response_model=VersionResponse)
def version(settings: Annotated[Settings, Depends(get_settings)]) -> VersionResponse:
    """Return the product and build version."""

    return VersionResponse(
        name=settings.app_name,
        version=__version__,
        build_sha=settings.build_sha,
    )
