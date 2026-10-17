"""Memory-layer metadata: who wrote an entry, the proposing turn and correction links.

Existing rows keep their meaning: earlier memory entries were written by the system or the
fictional seed, and earlier preferences were set by a learner or local operator.

Revision ID: 0004_memory_layers
Revises: 0003_bkt_tracing
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_memory_layers"
down_revision: str | None = "0003_bkt_tracing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("origin", sa.String(length=16), server_default="system", nullable=False)
        )
        batch_op.add_column(sa.Column("turn_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("supersedes_id", sa.String(length=64), nullable=True))
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("updated_by", sa.String(length=16), server_default="learner", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.drop_column("updated_by")
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.drop_column("supersedes_id")
        batch_op.drop_column("turn_id")
        batch_op.drop_column("origin")
