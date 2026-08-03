"""Top-level HTTP API router."""

from fastapi import APIRouter

from personal_ai_os.api.routes.health import router as health_router
from personal_ai_os.api.routes.version import router as version_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(version_router)
