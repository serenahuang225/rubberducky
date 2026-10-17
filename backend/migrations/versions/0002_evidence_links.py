"""Personal evidence links between a learner's observations and hypotheses.

Revision ID: 0002_evidence_links
Revises: 0001_initial
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_evidence_links"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite (id, learner_id) keys let evidence links reference only same-learner rows.
    with op.batch_alter_table("misconception_hypotheses", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            batch_op.f("uq_misconception_hypotheses_id_learner_id"), ["id", "learner_id"]
        )
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            batch_op.f("uq_observations_id_learner_id"), ["id", "learner_id"]
        )

    op.create_table(
        "evidence_links",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=64), nullable=False),
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("rationale", sa.String(length=200), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "polarity IN ('supports', 'contradicts')", name=op.f("ck_evidence_links_polarity")
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_evidence_links_provenance"),
        ),
        sa.CheckConstraint(
            "strength >= 0 AND strength <= 1", name=op.f("ck_evidence_links_strength_range")
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id", "learner_id"],
            ["misconception_hypotheses.id", "misconception_hypotheses.learner_id"],
            name=op.f("fk_evidence_links_hypothesis_id_learner_id_misconception_hypotheses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_evidence_links_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "learner_id"],
            ["observations.id", "observations.learner_id"],
            name=op.f("fk_evidence_links_observation_id_learner_id_observations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_links")),
        sa.UniqueConstraint(
            "hypothesis_id",
            "observation_id",
            name=op.f("uq_evidence_links_hypothesis_id_observation_id"),
        ),
    )
    with op.batch_alter_table("evidence_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_evidence_links_learner_id"), ["learner_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_links_learner_id"))
    op.drop_table("evidence_links")
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_observations_id_learner_id"), type_="unique")
    with op.batch_alter_table("misconception_hypotheses", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("uq_misconception_hypotheses_id_learner_id"), type_="unique"
        )
