"""Authenticated self-device lifecycle endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from personal_ai_os.api.identity_dependencies import (
    authentication_failure,
    get_identity_service,
    require_device_scopes,
)
from personal_ai_os.identity.contracts import (
    CredentialRotationResponse,
    DevicePrincipal,
    DeviceSelfResponse,
    HeartbeatRequest,
)
from personal_ai_os.identity.errors import (
    AuthenticationError,
    CapabilityEscalationError,
)
from personal_ai_os.identity.service import IdentityService

router = APIRouter(prefix="/api/v1/devices/me", tags=["devices"])
SelfReadPrincipal = Annotated[
    DevicePrincipal,
    Depends(require_device_scopes("device.self.read")),
]
HeartbeatPrincipal = Annotated[
    DevicePrincipal,
    Depends(require_device_scopes("device.heartbeat.write", "device.capabilities.report")),
]
RotationPrincipal = Annotated[
    DevicePrincipal,
    Depends(require_device_scopes("device.credential.rotate")),
]
ServiceDependency = Annotated[IdentityService, Depends(get_identity_service)]


@router.get("", response_model=DeviceSelfResponse)
def get_self(
    principal: SelfReadPrincipal,
    service: ServiceDependency,
) -> DeviceSelfResponse:
    """Return only the authenticated device's sanitized metadata."""

    try:
        return service.device_self(principal)
    except AuthenticationError as error:
        raise authentication_failure() from error


@router.post("/heartbeat", response_model=DeviceSelfResponse)
def heartbeat(
    request: HeartbeatRequest,
    principal: HeartbeatPrincipal,
    service: ServiceDependency,
) -> DeviceSelfResponse:
    """Record one bounded heartbeat and current approved capability subset."""

    try:
        return service.heartbeat(principal, request)
    except AuthenticationError as error:
        raise authentication_failure() from error
    except CapabilityEscalationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="capability report exceeds approved inventory",
        ) from error


@router.post("/credentials/rotate", response_model=CredentialRotationResponse)
def rotate_credential(
    principal: RotationPrincipal,
    service: ServiceDependency,
) -> CredentialRotationResponse:
    """Replace the exact credential used for this request and return the new value once."""

    try:
        issued = service.rotate_credential(principal)
    except AuthenticationError as error:
        raise authentication_failure() from error
    return CredentialRotationResponse(
        credential_id=issued.credential_id,
        credential=issued.raw,
    )
