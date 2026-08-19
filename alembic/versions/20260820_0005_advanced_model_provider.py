"""persist requested model profile and executed provider identity

Revision ID: 20260820_0005
Revises: 20260819_0004
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "20260820_0005"
down_revision = "20260819_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add forward-only audit columns without rewriting historical runs."""

    op.add_column("agent_runs", sa.Column("requested_model", sa.String(length=64), nullable=True))
    op.add_column("agent_runs", sa.Column("executed_provider", sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Return to the Phase 8 schema while preserving earlier migrations."""

    op.drop_column("agent_runs", "executed_provider")
    op.drop_column("agent_runs", "requested_model")
