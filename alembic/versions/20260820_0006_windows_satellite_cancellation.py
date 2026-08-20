"""admit durable Windows satellite cancellation requests

Revision ID: 20260820_0006
Revises: 20260820_0005
Create Date: 2026-08-20
"""

from alembic import op

revision = "20260820_0006"
down_revision = "20260820_0005"
branch_labels = None
depends_on = None

_PHASE_9_STATUS = (
    "status IN ('proposed', 'validated', 'denied', 'awaiting_approval', 'approved', "
    "'executing', 'cancel_requested', 'succeeded', 'failed', 'rejected', 'expired', "
    "'cancelled')"
)
_PHASE_8_STATUS = (
    "status IN ('proposed', 'validated', 'denied', 'awaiting_approval', 'approved', "
    "'executing', 'succeeded', 'failed', 'rejected', 'expired', 'cancelled')"
)


def upgrade() -> None:
    """Add one honest in-flight cancellation state without rewriting tool rows."""

    op.drop_constraint("ck_tool_calls_status", "tool_calls", type_="check")
    op.create_check_constraint("ck_tool_calls_status", "tool_calls", _PHASE_9_STATUS)


def downgrade() -> None:
    """Return to the Phase 8 status vocabulary after active work is reconciled."""

    op.drop_constraint("ck_tool_calls_status", "tool_calls", type_="check")
    op.create_check_constraint("ck_tool_calls_status", "tool_calls", _PHASE_8_STATUS)
