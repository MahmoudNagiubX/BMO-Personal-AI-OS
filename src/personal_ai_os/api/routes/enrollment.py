"""One-time device enrollment redemption endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from personal_ai_os.api.identity_dependencies import get_identity_service
from personal_ai_os.identity.contracts import (
    EnrollmentRedeemRequest,
    EnrollmentRedeemResponse,
)
from personal_ai_os.identity.errors import EnrollmentRejectedError
from personal_ai_os.identity.service import IdentityService

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])


@router.post(
    "/redeem",
    response_model=EnrollmentRedeemResponse,
    status_code=status.HTTP_201_CREATED,
)
def redeem_enrollment(
    request: EnrollmentRedeemRequest,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> EnrollmentRedeemResponse:
    """Consume one locally approved enrollment without accepting authority metadata."""

    try:
        issued = service.redeem_enrollment(request.code)
    except EnrollmentRejectedError as error:
        raise HTTPException(status_code=400, detail="invalid enrollment") from error
    return EnrollmentRedeemResponse(
        device_id=issued.device_id,
        credential_id=issued.credential_id,
        credential=issued.raw,
    )
