"""Durable scene operation log and the per-session scene revision counter.

Revision ID: 0006_scene_operations
Revises: 0005_tutor_turns
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_scene_operations"
down_revision: str | None = "0005_tutor_turns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("scene_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "scene_operations",
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("author_role", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column("move_id", sa.String(length=64), nullable=True),
        sa.Column("reverses_op_id", sa.String(length=64), nullable=True),
        sa.Column("consumes_op_id", sa.String(length=64), nullable=True),
        sa.Column("affected_object_ids", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("reversed_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "author_role IN ('student', 'tutor')",
            name=op.f("ck_scene_operations_author_role"),
        ),
        sa.CheckConstraint(
            "kind IN ('add_object', 'erase_object', 'undo', 'redo', 'undo_tutor_move')",
            name=op.f("ck_scene_operations_kind"),
        ),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_scene_operations_seq_positive")),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_scene_operations_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("learner_id", "id", name=op.f("pk_scene_operations")),
        sa.UniqueConstraint(
            "learner_id",
            "session_id",
            "seq",
            name=op.f("uq_scene_operations_learner_id_session_id_seq"),
        ),
    )
    op.create_index(op.f("ix_scene_operations_learner_id"), "scene_operations", ["learner_id"])
    op.create_index(op.f("ix_scene_operations_session_id"), "scene_operations", ["session_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_scene_operations_session_id"), table_name="scene_operations")
    op.drop_index(op.f("ix_scene_operations_learner_id"), table_name="scene_operations")
    op.drop_table("scene_operations")
    op.drop_column("sessions", "scene_revision")
