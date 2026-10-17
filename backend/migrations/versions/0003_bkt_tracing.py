"""Versioned BKT parameter sets and the derived counted-opportunity ledger.

Raw observations are untouched; these tables only hold parameters and derived updates
that can be rebuilt from raw evidence at any time.

Revision ID: 0003_bkt_tracing
Revises: 0002_evidence_links
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_bkt_tracing"
down_revision: str | None = "0002_evidence_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bkt_parameter_sets",
        sa.Column("parameter_version", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("p_init", sa.Float(), nullable=False),
        sa.Column("p_learn", sa.Float(), nullable=False),
        sa.Column("p_guess", sa.Float(), nullable=False),
        sa.Column("p_slip", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("calibrated", sa.Boolean(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "calibrated = 0 OR source = 'fitted'",
            name=op.f("ck_bkt_parameter_sets_calibrated_needs_fit"),
        ),
        sa.CheckConstraint(
            "source IN ('hand_set', 'fitted')", name=op.f("ck_bkt_parameter_sets_source")
        ),
        sa.CheckConstraint("p_guess + p_slip < 1", name=op.f("ck_bkt_parameter_sets_identifiable")),
        sa.CheckConstraint(
            "p_guess >= 0 AND p_guess <= 1", name=op.f("ck_bkt_parameter_sets_p_guess_range")
        ),
        sa.CheckConstraint(
            "p_init >= 0 AND p_init <= 1", name=op.f("ck_bkt_parameter_sets_p_init_range")
        ),
        sa.CheckConstraint(
            "p_learn >= 0 AND p_learn <= 1", name=op.f("ck_bkt_parameter_sets_p_learn_range")
        ),
        sa.CheckConstraint(
            "p_slip >= 0 AND p_slip <= 1", name=op.f("ck_bkt_parameter_sets_p_slip_range")
        ),
        sa.PrimaryKeyConstraint("parameter_version", name=op.f("pk_bkt_parameter_sets")),
    )
    op.create_table(
        "bkt_counted_opportunities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("parameter_version", sa.String(length=40), nullable=False),
        sa.Column("algorithm_version", sa.String(length=40), nullable=False),
        sa.Column("eligibility_version", sa.String(length=40), nullable=False),
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("opportunity_key", sa.String(length=160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("p_known_before", sa.Float(), nullable=False),
        sa.Column("p_correct_predicted", sa.Float(), nullable=False),
        sa.Column("observed_correct", sa.Boolean(), nullable=False),
        sa.Column("p_known_posterior", sa.Float(), nullable=False),
        sa.Column("p_known_after", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "p_correct_predicted >= 0 AND p_correct_predicted <= 1",
            name=op.f("ck_bkt_counted_opportunities_p_correct_predicted_range"),
        ),
        sa.CheckConstraint(
            "p_known_after >= 0 AND p_known_after <= 1",
            name=op.f("ck_bkt_counted_opportunities_p_known_after_range"),
        ),
        sa.CheckConstraint(
            "p_known_before >= 0 AND p_known_before <= 1",
            name=op.f("ck_bkt_counted_opportunities_p_known_before_range"),
        ),
        sa.CheckConstraint(
            "p_known_posterior >= 0 AND p_known_posterior <= 1",
            name=op.f("ck_bkt_counted_opportunities_p_known_posterior_range"),
        ),
        sa.CheckConstraint(
            "sequence >= 1", name=op.f("ck_bkt_counted_opportunities_sequence_positive")
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concepts.id"],
            name=op.f("fk_bkt_counted_opportunities_concept_id_concepts"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_bkt_counted_opportunities_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "learner_id"],
            ["observations.id", "observations.learner_id"],
            name=op.f("fk_bkt_counted_opportunities_observation_id_learner_id_observations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parameter_version"],
            ["bkt_parameter_sets.parameter_version"],
            name=op.f("fk_bkt_counted_opportunities_parameter_version_bkt_parameter_sets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bkt_counted_opportunities")),
        sa.UniqueConstraint(
            "learner_id",
            "parameter_version",
            "concept_id",
            "opportunity_key",
            name=op.f(
                "uq_bkt_counted_opportunities_learner_id_parameter_version_concept_id_opportunity_key"
            ),
        ),
        sa.UniqueConstraint(
            "learner_id",
            "parameter_version",
            "observation_id",
            name=op.f("uq_bkt_counted_opportunities_learner_id_parameter_version_observation_id"),
        ),
    )
    with op.batch_alter_table("bkt_counted_opportunities", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_bkt_counted_opportunities_learner_id"), ["learner_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("bkt_counted_opportunities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_bkt_counted_opportunities_learner_id"))

    op.drop_table("bkt_counted_opportunities")
    op.drop_table("bkt_parameter_sets")
