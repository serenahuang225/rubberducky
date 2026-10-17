"""Media event metadata: idempotency, one-final-per-utterance and bounded rates (no raw media).

Revision ID: 0011_media_events
Revises: 0010_cancellation_epoch
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_media_events"
down_revision: str | None = "0010_cancellation_epoch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_events",
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("utterance_id", sa.String(length=64), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("final_key", sa.String(length=64), nullable=True),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("base_epoch", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('image_snapshot', 'transcript', 'weak_context')",
            name=op.f("ck_media_events_kind"),
        ),
        sa.CheckConstraint(
            "source IN ('device', 'simulated')", name=op.f("ck_media_events_source")
        ),
        sa.CheckConstraint(
            "base_revision >= 0 AND base_epoch >= 0", name=op.f("ck_media_events_scope_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_media_events_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("learner_id", "event_id", name=op.f("pk_media_events")),
        sa.UniqueConstraint(
            "learner_id",
            "session_id",
            "final_key",
            name=op.f("uq_media_events_learner_id_session_id_final_key"),
        ),
    )
    op.create_index(op.f("ix_media_events_session_id"), "media_events", ["session_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_media_events_session_id"), table_name="media_events")
    op.drop_table("media_events")
