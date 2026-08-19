"""add durable Phase 7 text conversation state

Revision ID: 20260819_0003
Revises: 20260819_0002
Create Date: 2026-08-19
"""

import sqlalchemy as sa

from alembic import op

revision = "20260819_0003"
down_revision = "20260819_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable conversations, sessions, messages, runs, and replay events."""

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_device_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_conversations_status"),
        sa.CheckConstraint(
            "title IS NULL OR length(title) BETWEEN 1 AND 200", name="ck_conversations_title"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_owner_updated",
        "conversations",
        ["owner_id", "updated_at", "id"],
    )

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'closed')", name="ck_conversation_sessions_status"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_sessions_owner_device",
        "conversation_sessions",
        ["owner_id", "device_id", "status"],
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("author_device_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role"),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 4000", name="ck_conversation_messages_content"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "ordinal", name="uq_conversation_message_ordinal"),
    )
    op.create_index(
        "ix_conversation_messages_conversation_created",
        "conversation_messages",
        ["conversation_id", "ordinal"],
    )
    op.create_index(
        "uq_conversation_message_client_id",
        "conversation_messages",
        ["conversation_id", "author_device_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("request_device_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_message_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_request_id", sa.String(length=128), nullable=True),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("model_digest", sa.String(length=80), nullable=True),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("prompt_usage", sa.Integer(), nullable=True),
        sa.Column("output_usage", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("context_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("event_sequence_start", sa.Integer(), nullable=True),
        sa.Column("event_sequence_end", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'succeeded', 'failed', "
            "'cancelled')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["trigger_message_id"], ["conversation_messages.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runs_conversation_created", "agent_runs", ["conversation_id", "created_at"]
    )
    op.create_index(
        "uq_agent_runs_one_active_per_conversation",
        "agent_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancel_requested')"),
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_run_events_sequence"),
        sa.CheckConstraint("length(event_type) BETWEEN 1 AND 64", name="ck_run_events_type"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_run_events_session_sequence"),
    )
    op.create_index("ix_run_events_session_sequence", "run_events", ["session_id", "sequence"])


def downgrade() -> None:
    """Remove only Phase 7 tables and return to the Phase 6 head."""

    op.drop_index("ix_run_events_session_sequence", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("uq_agent_runs_one_active_per_conversation", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("uq_conversation_message_client_id", table_name="conversation_messages")
    op.drop_index(
        "ix_conversation_messages_conversation_created", table_name="conversation_messages"
    )
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversation_sessions_owner_device", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_table("conversations")
