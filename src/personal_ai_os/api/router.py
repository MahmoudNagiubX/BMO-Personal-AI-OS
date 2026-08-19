"""Top-level HTTP API router."""

from fastapi import APIRouter

from personal_ai_os.api.routes.approvals import router as approvals_router
from personal_ai_os.api.routes.audit import router as audit_router
from personal_ai_os.api.routes.conversations import router as conversations_router
from personal_ai_os.api.routes.devices import router as devices_router
from personal_ai_os.api.routes.enrollment import router as enrollment_router
from personal_ai_os.api.routes.health import router as health_router
from personal_ai_os.api.routes.tools import router as tools_router
from personal_ai_os.api.routes.version import router as version_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(version_router)
api_router.include_router(enrollment_router)
api_router.include_router(devices_router)
api_router.include_router(conversations_router)
api_router.include_router(tools_router)
api_router.include_router(approvals_router)
api_router.include_router(audit_router)
