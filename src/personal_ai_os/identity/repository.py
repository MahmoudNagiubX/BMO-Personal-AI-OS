"""Persistence operations for the Phase 6 identity service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

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


class IdentityRepository:
    """Small SQLAlchemy repository; transaction ownership stays in the service."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def owner_count(self) -> int:
        return len(self.session.scalars(select(Owner.id)).all())

    def owner(self, owner_id: UUID) -> Owner | None:
        return self.session.get(Owner, owner_id)

    def add(self, *rows: object) -> None:
        self.session.add_all(rows)

    def flush(self) -> None:
        self.session.flush()

    def locked_enrollment_by_hash(self, code_hash: str) -> Enrollment | None:
        statement = select(Enrollment).where(Enrollment.code_hash == code_hash).with_for_update()
        return self.session.scalar(statement)

    def enrollment_scopes(self, enrollment_id: UUID) -> list[str]:
        statement = select(EnrollmentScope.scope).where(
            EnrollmentScope.enrollment_id == enrollment_id
        )
        return list(self.session.scalars(statement))

    def enrollment_capabilities(self, enrollment_id: UUID) -> list[str]:
        statement = select(EnrollmentCapability.capability).where(
            EnrollmentCapability.enrollment_id == enrollment_id
        )
        return list(self.session.scalars(statement))

    def credential_identity(
        self, public_id: str, *, lock: bool = False
    ) -> tuple[DeviceCredential, Device, Owner] | None:
        statement: Select[tuple[DeviceCredential, Device, Owner]] = (
            select(DeviceCredential, Device, Owner)
            .join(Device, Device.id == DeviceCredential.device_id)
            .join(Owner, Owner.id == Device.owner_id)
            .where(DeviceCredential.public_id == public_id)
        )
        if lock:
            statement = statement.with_for_update(of=DeviceCredential)
        row = self.session.execute(statement).one_or_none()
        if row is None:
            return None
        return row[0], row[1], row[2]

    def locked_credential(self, credential_id: UUID) -> DeviceCredential | None:
        statement = (
            select(DeviceCredential).where(DeviceCredential.id == credential_id).with_for_update()
        )
        return self.session.scalar(statement)

    def locked_device(self, device_id: UUID) -> Device | None:
        statement = select(Device).where(Device.id == device_id).with_for_update()
        return self.session.scalar(statement)

    def device(self, device_id: UUID) -> Device | None:
        return self.session.get(Device, device_id)

    def device_scopes(self, device_id: UUID) -> list[str]:
        statement = select(DeviceScope.scope).where(DeviceScope.device_id == device_id)
        return list(self.session.scalars(statement))

    def device_capability_rows(self, device_id: UUID) -> list[DeviceCapability]:
        statement = select(DeviceCapability).where(DeviceCapability.device_id == device_id)
        return list(self.session.scalars(statement))

    def clear_reported_capabilities(self, device_id: UUID) -> None:
        self.session.execute(
            update(DeviceCapability)
            .where(DeviceCapability.device_id == device_id)
            .values(reported=False, last_reported_at=None)
        )

    def devices(self) -> list[Device]:
        return list(self.session.scalars(select(Device).order_by(Device.created_at, Device.id)))

    def active_credentials(self, device_id: UUID, *, lock: bool = False) -> list[DeviceCredential]:
        statement = select(DeviceCredential).where(
            DeviceCredential.device_id == device_id,
            DeviceCredential.revoked_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return list(self.session.scalars(statement))
