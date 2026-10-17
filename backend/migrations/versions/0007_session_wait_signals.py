"""Explicit "Still thinking" presses per session (a request for space, not evidence).

Revision ID: 0007_session_wait_signals
Revises: 0006_scene_operations
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_session_wait_signals"
down_revision: str | None = "0006_scene_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_wait_signals",
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("still_thinking_at", sa.DateTime(), nullable=True),
        sa.Column("still_thinking_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "still_thinking_count >= 0",
            name=op.f("ck_session_wait_signals_still_thinking_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_session_wait_signals_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("learner_id", "session_id", name=op.f("pk_session_wait_signals")),
    )


def downgrade() -> None:
    op.drop_table("session_wait_signals")
