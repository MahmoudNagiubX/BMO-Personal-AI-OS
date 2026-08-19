"""Typed Phase 6 identity and device API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PHASE_6_SCOPES = frozenset(
    {
        "device.self.read",
        "device.heartbeat.write",
        "device.capabilities.report",
        "device.credential.rotate",
    }
)
DeviceKind = Literal[
    "windows_client",
    "android_client",
    "room_node",
    "windows_satellite",
    "browser_worker",
    "internal_service",
    "bridge",
]
DevicePlatform = Literal["windows", "android", "linux", "embedded", "service"]
CapabilityId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"),
]
SoftwareVersion = Annotated[str, Field(min_length=1, max_length=64)]


class StrictContract(BaseModel):
    """Reject unrecognized fields at every security boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DevicePrincipal(StrictContract):
    """Authenticated device identity passed to scoped handlers."""

    owner_id: UUID
    device_id: UUID
    credential_id: UUID
    scopes: frozenset[str]


class EnrollmentRedeemRequest(StrictContract):
    """The only device-controlled enrollment input."""

    code: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class EnrollmentRedeemResponse(StrictContract):
    """One-time enrollment result containing the initial raw credential."""

    device_id: UUID
    credential: str
    credential_id: UUID


class CredentialRotationResponse(StrictContract):
    """One-time rotation result containing the replacement raw credential."""

    credential: str
    credential_id: UUID


class HeartbeatRequest(StrictContract):
    """Bounded current device state accepted by heartbeat."""

    software_version: SoftwareVersion | None = None
    reported_capabilities: list[CapabilityId] = Field(default_factory=list, max_length=64)

    @field_validator("reported_capabilities")
    @classmethod
    def reject_duplicate_capabilities(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("reported_capabilities must be unique")
        return value


class DeviceSelfResponse(StrictContract):
    """Sanitized self-only device metadata."""

    id: UUID
    owner_id: UUID
    display_name: str
    device_kind: str
    platform: str
    status: str
    software_version: str | None
    last_heartbeat_at: datetime | None
    approved_scopes: list[str]
    approved_capabilities: list[str]
    reported_capabilities: list[str]


class EnrollmentGrant(StrictContract):
    """Locally approved immutable device attributes for one enrollment."""

    owner_id: UUID
    display_name: str = Field(min_length=1, max_length=100)
    device_kind: DeviceKind
    platform: DevicePlatform
    software_version: SoftwareVersion | None = None
    scopes: list[str] = Field(min_length=1, max_length=4)
    capabilities: list[CapabilityId] = Field(default_factory=list, max_length=64)
    ttl_minutes: int = Field(default=10, ge=1, le=30)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("scopes must be unique")
        unsupported = set(value) - PHASE_6_SCOPES
        if unsupported:
            raise ValueError("unsupported Phase 6 scope")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value
