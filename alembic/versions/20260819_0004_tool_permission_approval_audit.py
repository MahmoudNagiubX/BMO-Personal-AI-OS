"""add Phase 8 tool, permission, approval, observation, and audit state

Revision ID: 20260819_0004
Revises: 20260819_0003
Create Date: 2026-08-19
"""

import sqlalchemy as sa

from alembic import op

revision = "20260819_0004"
down_revision = "20260819_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable Phase 8 authority and evidence rows."""

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("argument_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=True),
        sa.Column("reason_code", sa.String(length=96), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposed', 'validated', 'denied', 'awaiting_approval', 'approved', "
            "'executing', 'succeeded', 'failed', 'rejected', 'expired', 'cancelled')",
            name="ck_tool_calls_status",
        ),
        sa.CheckConstraint(
            "risk_level IN ('read', 'reversible', 'consequential', 'critical', "
            "'forbidden_autonomous')",
            name="ck_tool_calls_risk",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "device_id",
            "tool_name",
            "idempotency_key",
            name="uq_tool_calls_idempotency",
        ),
    )
    op.create_index("ix_tool_calls_owner_created", "tool_calls", ["owner_id", "created_at"])
    op.create_index("ix_tool_calls_run_status", "tool_calls", ["run_id", "status"])

    op.create_table(
        "permission_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=96), nullable=False),
        sa.Column("argument_digest", sa.String(length=64), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_permission_decisions_tool_call", "permission_decisions", ["tool_call_id", "decided_at"]
    )

    op.create_table(
        "tool_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("requesting_device_id", sa.Uuid(), nullable=False),
        sa.Column("decision_device_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("argument_digest", sa.String(length=64), nullable=False),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled', 'consumed')",
            name="ck_tool_approvals_status",
        ),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requesting_device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_id"),
    )
    op.create_index(
        "ix_tool_approvals_owner_status", "tool_approvals", ["owner_id", "status", "expires_at"]
    )

    op.create_table(
        "tool_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("verification_json", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_id"),
    )

    op.create_table(
        "tool_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("tool_call_id", sa.Uuid(), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_version", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("reason_code", sa.String(length=96), nullable=True),
        sa.Column("argument_digest", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("immutable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_audit_events_owner_time", "tool_audit_events", ["owner_id", "occurred_at"]
    )
    op.create_index(
        "ix_tool_audit_events_tool_call_time", "tool_audit_events", ["tool_call_id", "occurred_at"]
    )

    op.create_table(
        "tool_rate_buckets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_rate_buckets_device_tool", "tool_rate_buckets", ["device_id", "tool_name"]
    )


def downgrade() -> None:
    """Remove only Phase 8 tables and return to the Phase 7 head."""

    op.drop_index("ix_tool_rate_buckets_device_tool", table_name="tool_rate_buckets")
    op.drop_table("tool_rate_buckets")
    op.drop_index("ix_tool_audit_events_tool_call_time", table_name="tool_audit_events")
    op.drop_index("ix_tool_audit_events_owner_time", table_name="tool_audit_events")
    op.drop_table("tool_audit_events")
    op.drop_table("tool_observations")
    op.drop_index("ix_tool_approvals_owner_status", table_name="tool_approvals")
    op.drop_table("tool_approvals")
    op.drop_index("ix_permission_decisions_tool_call", table_name="permission_decisions")
    op.drop_table("permission_decisions")
    op.drop_index("ix_tool_calls_run_status", table_name="tool_calls")
    op.drop_index("ix_tool_calls_owner_created", table_name="tool_calls")
    op.drop_table("tool_calls")
