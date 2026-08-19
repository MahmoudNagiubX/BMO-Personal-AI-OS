"""Owner identity and device enrollment domain."""

from personal_ai_os.identity.contracts import (
    ACTIVE_DEVICE_SCOPES,
    PHASE_6_SCOPES,
    PHASE_7_SCOPES,
    PHASE_8_SCOPES,
    DevicePrincipal,
)
from personal_ai_os.identity.service import IdentityService

__all__ = [
    "ACTIVE_DEVICE_SCOPES",
    "PHASE_6_SCOPES",
    "PHASE_7_SCOPES",
    "PHASE_8_SCOPES",
    "DevicePrincipal",
    "IdentityService",
]
