"""SQLAlchemy models for owner and device identity."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from personal_ai_os.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-created rows."""

    return datetime.now(UTC)


class Owner(Base):
    """Single-owner identity record bootstrapped through a local CLI."""

    __tablename__ = "owners"
    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="ck_owners_status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
    )


class Device(Base):
    """An independently revocable device owned by one owner."""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_devices_status"),
        CheckConstraint("length(display_name) BETWEEN 1 AND 100", name="ck_device_name"),
        CheckConstraint("length(device_kind) BETWEEN 1 AND 32", name="ck_device_kind"),
        CheckConstraint("length(platform) BETWEEN 1 AND 32", name="ck_device_platform"),
        CheckConstraint(
            "software_version IS NULL OR length(software_version) BETWEEN 1 AND 64",
            name="ck_device_software_version",
        ),
        Index("ix_devices_owner_status", "owner_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    software_version: Mapped[str | None] = mapped_column(String(64))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
    )


class DeviceCredential(Base):
    """Hash-only opaque credential associated with one device."""

    __tablename__ = "device_credentials"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_device_credentials_public_id"),
        CheckConstraint("length(secret_hash) = 64", name="ck_credential_hash_length"),
        Index("ix_device_credentials_device_active", "device_id", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("device_credentials.id", ondelete="SET NULL")
    )


class DeviceScope(Base):
    """Owner-approved transport scope for one device."""

    __tablename__ = "device_scopes"

    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)


class DeviceCapability(Base):
    """Approved capability plus its current heartbeat-reporting state."""

    __tablename__ = "device_capabilities"

    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    reported: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    last_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Enrollment(Base):
    """Hash-only short-lived approval for exactly one device enrollment."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_enrollments_code_hash"),
        CheckConstraint("length(code_hash) = 64", name="ck_enrollment_hash_length"),
        Index("ix_enrollments_owner_expires", "owner_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    software_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrollmentScope(Base):
    """Scope approved locally for a pending enrollment."""

    __tablename__ = "enrollment_scopes"

    enrollment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("enrollments.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)


class EnrollmentCapability(Base):
    """Capability approved locally for a pending enrollment."""

    __tablename__ = "enrollment_capabilities"

    enrollment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("enrollments.id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
