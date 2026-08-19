"""add identity and device enrollment

Revision ID: 20260819_0002
Revises: 20260803_0001
Create Date: 2026-08-19
"""

import sqlalchemy as sa

from alembic import op

revision = "20260819_0002"
down_revision = "20260803_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the normalized Phase 6 identity boundary."""

    op.create_table(
        "owners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton_key", sa.Integer(), server_default="1", nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_owners_status"),
        sa.CheckConstraint("singleton_key = 1", name="ck_owners_singleton_key"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("singleton_key", name="uq_owners_singleton_key"),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("device_kind", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("software_version", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_devices_status"),
        sa.CheckConstraint("length(display_name) BETWEEN 1 AND 100", name="ck_device_name"),
        sa.CheckConstraint("length(device_kind) BETWEEN 1 AND 32", name="ck_device_kind"),
        sa.CheckConstraint("length(platform) BETWEEN 1 AND 32", name="ck_device_platform"),
        sa.CheckConstraint(
            "software_version IS NULL OR length(software_version) BETWEEN 1 AND 64",
            name="ck_device_software_version",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_owner_status", "devices", ["owner_id", "status"])
    op.create_table(
        "device_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("length(secret_hash) = 64", name="ck_credential_hash_length"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["rotated_from_id"], ["device_credentials.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_device_credentials_public_id"),
    )
    op.create_index(
        "ix_device_credentials_device_active",
        "device_credentials",
        ["device_id", "revoked_at"],
    )
    op.create_table(
        "device_scopes",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "scope"),
    )
    op.create_table(
        "device_capabilities",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("reported", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "capability"),
    )
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("device_kind", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("software_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(code_hash) = 64", name="ck_enrollment_hash_length"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_enrollments_code_hash"),
    )
    op.create_index("ix_enrollments_owner_expires", "enrollments", ["owner_id", "expires_at"])
    op.create_table(
        "enrollment_scopes",
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("enrollment_id", "scope"),
    )
    op.create_table(
        "enrollment_capabilities",
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("enrollment_id", "capability"),
    )


def downgrade() -> None:
    """Remove only Phase 6 identity tables in dependency-safe order."""

    op.drop_table("enrollment_capabilities")
    op.drop_table("enrollment_scopes")
    op.drop_index("ix_enrollments_owner_expires", table_name="enrollments")
    op.drop_table("enrollments")
    op.drop_table("device_capabilities")
    op.drop_table("device_scopes")
    op.drop_index("ix_device_credentials_device_active", table_name="device_credentials")
    op.drop_table("device_credentials")
    op.drop_index("ix_devices_owner_status", table_name="devices")
    op.drop_table("devices")
    op.drop_table("owners")
