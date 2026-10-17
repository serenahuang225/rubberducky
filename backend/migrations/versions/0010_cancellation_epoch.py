"""Cancellation epoch: invalidates pending tutor output without moving the session revision.

Revision ID: 0010_cancellation_epoch
Revises: 0009_persona_comfort
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_cancellation_epoch"
down_revision: str | None = "0009_persona_comfort"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(
            sa.Column("cancellation_epoch", sa.Integer(), server_default="0", nullable=False)
        )
    with op.batch_alter_table("tutor_turns") as batch:
        batch.add_column(sa.Column("base_epoch", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("tutor_turns") as batch:
        batch.drop_column("base_epoch")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("cancellation_epoch")
