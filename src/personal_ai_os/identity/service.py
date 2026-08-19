"""Transactional owner identity and device lifecycle rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from personal_ai_os.identity.contracts import (
    DevicePrincipal,
    DeviceSelfResponse,
    EnrollmentGrant,
    HeartbeatRequest,
)
from personal_ai_os.identity.errors import (
    AuthenticationError,
    CapabilityEscalationError,
    DeviceNotFoundError,
    EnrollmentRejectedError,
    OwnerBootstrapError,
    ScopeDeniedError,
)
from personal_ai_os.identity.models import (
    Device,
    DeviceCapability,
    DeviceCredential,
    DeviceScope,
    Enrollment,
    EnrollmentCapability,
    EnrollmentScope,
    Owner,
)
from personal_ai_os.identity.repository import IdentityRepository
from personal_ai_os.identity.security import (
    GeneratedCredential,
    generate_device_credential,
    generate_enrollment_code,
    hash_secret,
    parse_device_credential,
    verify_secret,
)

Clock = Callable[[], datetime]
EnrollmentCodeFactory = Callable[[], str]
CredentialFactory = Callable[[], GeneratedCredential]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class IssuedEnrollment:
    """One-time code returned only to the local owner operation."""

    enrollment_id: UUID
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    """One-time raw credential returned only at enrollment or rotation."""

    device_id: UUID
    credential_id: UUID
    raw: str


class IdentityService:
    """Fail-closed Phase 6 identity and device business logic."""

    def __init__(
        self,
        session: Session,
        *,
        clock: Clock = _utc_now,
        enrollment_code_factory: EnrollmentCodeFactory = generate_enrollment_code,
        credential_factory: CredentialFactory = generate_device_credential,
    ) -> None:
        self.session = session
        self.repository = IdentityRepository(session)
        self.clock = clock
        self.enrollment_code_factory = enrollment_code_factory
        self.credential_factory = credential_factory

    def bootstrap_owner(self, display_name: str) -> Owner:
        """Create the first owner locally and refuse multi-owner bootstrap."""

        normalized_name = display_name.strip()
        if not 1 <= len(normalized_name) <= 100:
            raise OwnerBootstrapError("owner display name must be between 1 and 100 characters")
        try:
            with self.session.begin():
                if self.repository.owner_count() != 0:
                    raise OwnerBootstrapError("owner bootstrap is already complete")
                owner = Owner(display_name=normalized_name, status="active")
                self.repository.add(owner)
                self.repository.flush()
        except IntegrityError:
            raise OwnerBootstrapError("owner bootstrap is already complete") from None
        return owner

    def create_enrollment(self, grant: EnrollmentGrant) -> IssuedEnrollment:
        """Create one immutable local approval and return its code once."""

        code = self.enrollment_code_factory()
        if len(code) < 20:
            raise ValueError("enrollment code factory returned insufficient entropy")
        now = self.clock()
        expires_at = now + timedelta(minutes=grant.ttl_minutes)
        with self.session.begin():
            owner = self.repository.owner(grant.owner_id)
            if owner is None or owner.status != "active":
                raise EnrollmentRejectedError("owner is unavailable")
            enrollment = Enrollment(
                owner_id=grant.owner_id,
                code_hash=hash_secret(code),
                display_name=grant.display_name,
                device_kind=grant.device_kind,
                platform=grant.platform,
                software_version=grant.software_version,
                expires_at=expires_at,
            )
            self.repository.add(enrollment)
            self.repository.flush()
            self.repository.add(
                *(
                    EnrollmentScope(enrollment_id=enrollment.id, scope=scope)
                    for scope in grant.scopes
                ),
                *(
                    EnrollmentCapability(enrollment_id=enrollment.id, capability=capability)
                    for capability in grant.capabilities
                ),
            )
        return IssuedEnrollment(enrollment.id, code, expires_at)

    def redeem_enrollment(self, code: str) -> IssuedCredential:
        """Consume one enrollment under a database row lock and issue one credential."""

        now = self.clock()
        with self.session.begin():
            enrollment = self.repository.locked_enrollment_by_hash(hash_secret(code))
            if (
                enrollment is None
                or enrollment.consumed_at is not None
                or _aware_utc(enrollment.expires_at) <= _aware_utc(now)
            ):
                raise EnrollmentRejectedError("invalid enrollment")
            owner = self.repository.owner(enrollment.owner_id)
            if owner is None or owner.status != "active":
                raise EnrollmentRejectedError("invalid enrollment")
            approved_scopes = self.repository.enrollment_scopes(enrollment.id)
            approved_capabilities = self.repository.enrollment_capabilities(enrollment.id)
            generated = self.credential_factory()
            device = Device(
                owner_id=enrollment.owner_id,
                display_name=enrollment.display_name,
                device_kind=enrollment.device_kind,
                platform=enrollment.platform,
                software_version=enrollment.software_version,
                status="active",
            )
            self.repository.add(device)
            self.repository.flush()
            credential = DeviceCredential(
                device_id=device.id,
                public_id=generated.public_id,
                secret_hash=generated.secret_hash,
            )
            self.repository.add(
                credential,
                *(DeviceScope(device_id=device.id, scope=scope) for scope in approved_scopes),
                *(
                    DeviceCapability(device_id=device.id, capability=capability)
                    for capability in approved_capabilities
                ),
            )
            enrollment.consumed_at = now
            self.repository.flush()
        return IssuedCredential(device.id, credential.id, generated.raw)

    def authenticate(self, raw_credential: str) -> DevicePrincipal:
        """Authenticate an opaque credential and return a typed principal."""

        parsed = parse_device_credential(raw_credential)
        if parsed is None:
            raise AuthenticationError("invalid device credential")
        public_id, secret = parsed
        now = self.clock()
        with self.session.begin():
            identity = self.repository.credential_identity(public_id, lock=True)
            if identity is None:
                raise AuthenticationError("invalid device credential")
            credential, device, owner = identity
            if (
                not verify_secret(secret, credential.secret_hash)
                or credential.revoked_at is not None
                or device.status != "active"
                or owner.status != "active"
            ):
                raise AuthenticationError("invalid device credential")
            scopes = frozenset(self.repository.device_scopes(device.id))
            credential.last_used_at = now
        return DevicePrincipal(
            owner_id=owner.id,
            device_id=device.id,
            credential_id=credential.id,
            scopes=scopes,
        )

    @staticmethod
    def require_scopes(principal: DevicePrincipal, *required: str) -> None:
        """Fail closed unless every required Phase 6 scope is present."""

        if not set(required).issubset(principal.scopes):
            raise ScopeDeniedError("insufficient scope")

    def device_self(self, principal: DevicePrincipal) -> DeviceSelfResponse:
        """Return sanitized metadata for only the authenticated device."""

        with self.session.begin():
            device = self.repository.device(principal.device_id)
            if device is None or device.status != "active":
                raise AuthenticationError("invalid device credential")
            scopes = sorted(self.repository.device_scopes(device.id))
            capability_rows = self.repository.device_capability_rows(device.id)
            approved = sorted(row.capability for row in capability_rows)
            reported = sorted(row.capability for row in capability_rows if row.reported)
            return DeviceSelfResponse(
                id=device.id,
                owner_id=device.owner_id,
                display_name=device.display_name,
                device_kind=device.device_kind,
                platform=device.platform,
                status=device.status,
                software_version=device.software_version,
                last_heartbeat_at=device.last_heartbeat_at,
                approved_scopes=scopes,
                approved_capabilities=approved,
                reported_capabilities=reported,
            )

    def heartbeat(
        self, principal: DevicePrincipal, request: HeartbeatRequest
    ) -> DeviceSelfResponse:
        """Update one bounded current heartbeat and approved capability subset."""

        now = self.clock()
        with self.session.begin():
            device = self.repository.locked_device(principal.device_id)
            if device is None or device.status != "active":
                raise AuthenticationError("invalid device credential")
            capability_rows = self.repository.device_capability_rows(device.id)
            approved = {row.capability for row in capability_rows}
            reported = set(request.reported_capabilities)
            if not reported.issubset(approved):
                raise CapabilityEscalationError("capability report exceeds approved inventory")
            self.repository.clear_reported_capabilities(device.id)
            for row in capability_rows:
                if row.capability in reported:
                    row.reported = True
                    row.last_reported_at = now
            device.last_heartbeat_at = now
            if request.software_version is not None:
                device.software_version = request.software_version
        return self.device_self(principal)

    def rotate_credential(self, principal: DevicePrincipal) -> IssuedCredential:
        """Atomically replace only the credential used for this request."""

        now = self.clock()
        with self.session.begin():
            device = self.repository.locked_device(principal.device_id)
            if device is None or device.status != "active":
                raise AuthenticationError("invalid device credential")
            old = self.repository.locked_credential(principal.credential_id)
            if old is None or old.device_id != principal.device_id or old.revoked_at is not None:
                raise AuthenticationError("invalid device credential")
            generated = self.credential_factory()
            replacement = DeviceCredential(
                device_id=device.id,
                public_id=generated.public_id,
                secret_hash=generated.secret_hash,
                rotated_from_id=old.id,
            )
            old.revoked_at = now
            self.repository.add(replacement)
            self.repository.flush()
        return IssuedCredential(device.id, replacement.id, generated.raw)

    def list_devices(self) -> list[DeviceSelfResponse]:
        """Return sanitized registry rows to a local administrative CLI."""

        with self.session.begin():
            result: list[DeviceSelfResponse] = []
            for device in self.repository.devices():
                capability_rows = self.repository.device_capability_rows(device.id)
                result.append(
                    DeviceSelfResponse(
                        id=device.id,
                        owner_id=device.owner_id,
                        display_name=device.display_name,
                        device_kind=device.device_kind,
                        platform=device.platform,
                        status=device.status,
                        software_version=device.software_version,
                        last_heartbeat_at=device.last_heartbeat_at,
                        approved_scopes=sorted(self.repository.device_scopes(device.id)),
                        approved_capabilities=sorted(row.capability for row in capability_rows),
                        reported_capabilities=sorted(
                            row.capability for row in capability_rows if row.reported
                        ),
                    )
                )
            return result

    def revoke_device(self, device_id: UUID) -> None:
        """Soft-revoke one device and all of only its live credentials."""

        now = self.clock()
        with self.session.begin():
            device = self.repository.locked_device(device_id)
            if device is None:
                raise DeviceNotFoundError("device does not exist")
            device.status = "revoked"
            for credential in self.repository.active_credentials(device.id, lock=True):
                credential.revoked_at = now
