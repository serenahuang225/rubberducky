"""Learner corrections (original preserved) and content-free deletion tombstones.

Revision ID: 0008_memory_agency
Revises: 0007_session_wait_signals
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_memory_agency"
down_revision: str | None = "0007_session_wait_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_corrections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("original_correct", sa.Boolean(), nullable=False),
        sa.Column("corrected_correct", sa.Boolean(), nullable=False),
        sa.Column("original_assessment_outcome", sa.String(length=16), nullable=True),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("corrected_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_evidence_corrections_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_evidence_corrections_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "learner_id"],
            ["observations.id", "observations.learner_id"],
            name=op.f("fk_evidence_corrections_observation_id_learner_id_observations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_corrections")),
        sa.UniqueConstraint(
            "learner_id",
            "observation_id",
            name=op.f("uq_evidence_corrections_learner_id_observation_id"),
        ),
    )
    op.create_index(
        op.f("ix_evidence_corrections_learner_id"),
        "evidence_corrections",
        ["learner_id"],
        unique=False,
    )
    op.create_table(
        "deletion_tombstones",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("record_kind", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('learner_deleted', 'source_deleted', 'session_deleted', 'profile_deleted')",
            name=op.f("ck_deletion_tombstones_reason"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_tombstones")),
        sa.UniqueConstraint(
            "learner_id", "record_id", name=op.f("uq_deletion_tombstones_learner_id_record_id")
        ),
    )
    op.create_index(
        op.f("ix_deletion_tombstones_learner_id"),
        "deletion_tombstones",
        ["learner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_deletion_tombstones_record_id"),
        "deletion_tombstones",
        ["record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("deletion_tombstones")
    op.drop_table("evidence_corrections")
