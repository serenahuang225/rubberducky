"""Reserved tutor turns with idempotency keys, revisions, plans and results.

Revision ID: 0005_tutor_turns
Revises: 0004_memory_layers
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_tutor_turns"
down_revision: str | None = "0004_memory_layers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tutor_turns",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("committed_revision", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "base_revision >= 0", name=op.f("ck_tutor_turns_base_revision_nonnegative")
        ),
        sa.CheckConstraint("kind IN ('check_in', 'work')", name=op.f("ck_tutor_turns_kind")),
        sa.CheckConstraint(
            "status IN ('pending', 'committed', 'rejected', 'failed', 'superseded')",
            name=op.f("ck_tutor_turns_status"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_tutor_turns_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_tutor_turns_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_turns")),
        sa.UniqueConstraint(
            "learner_id",
            "idempotency_key",
            name=op.f("uq_tutor_turns_learner_id_idempotency_key"),
        ),
    )
    op.create_index(op.f("ix_tutor_turns_learner_id"), "tutor_turns", ["learner_id"])
    op.create_index(op.f("ix_tutor_turns_session_id"), "tutor_turns", ["session_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_tutor_turns_session_id"), table_name="tutor_turns")
    op.drop_index(op.f("ix_tutor_turns_learner_id"), table_name="tutor_turns")
    op.drop_table("tutor_turns")
