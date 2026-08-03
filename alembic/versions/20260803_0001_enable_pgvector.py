"""enable pgvector extension

Revision ID: 20260803_0001
Revises:
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable pgvector without creating product tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Remove the empty Phase 2 extension baseline."""

    op.execute("DROP EXTENSION IF EXISTS vector")
