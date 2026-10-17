"""Initial schema: learners, credentials, curriculum, evidence, beliefs, config and scenes.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "concepts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_concepts")),
    )
    op.create_table(
        "learners",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("is_fictional", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_learners_provenance")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learners")),
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_credentials_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credentials")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_credentials_token_hash")),
    )
    with op.batch_alter_table("credentials", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_credentials_learner_id"), ["learner_id"], unique=False)

    op.create_table(
        "learning_objectives",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('procedure', 'explanation', 'transfer')",
            name=op.f("ck_learning_objectives_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name=op.f("fk_learning_objectives_concept_id_concepts")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_objectives")),
    )
    op.create_table(
        "mastery_estimates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=40), nullable=False),
        sa.Column("algorithm_version", sa.String(length=40), nullable=False),
        sa.Column("parameter_version", sa.String(length=40), nullable=False),
        sa.Column("p_known", sa.Float(), nullable=False),
        sa.Column("calibrated", sa.Boolean(), nullable=False),
        sa.Column("source_observation_ids", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_mastery_estimates_provenance"),
        ),
        sa.CheckConstraint(
            "p_known >= 0 AND p_known <= 1", name=op.f("ck_mastery_estimates_p_known_range")
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name=op.f("fk_mastery_estimates_concept_id_concepts")
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_mastery_estimates_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mastery_estimates")),
    )
    with op.batch_alter_table("mastery_estimates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_mastery_estimates_learner_id"), ["learner_id"], unique=False
        )

    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_pairing_codes_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pairing_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_pairing_codes_code_hash")),
    )
    with op.batch_alter_table("pairing_codes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pairing_codes_learner_id"), ["learner_id"], unique=False
        )

    op.create_table(
        "preferences",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_preferences_provenance")
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_preferences_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preferences")),
        sa.UniqueConstraint("learner_id", "key", name=op.f("uq_preferences_learner_id_key")),
    )
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_preferences_learner_id"), ["learner_id"], unique=False)

    op.create_table(
        "prerequisite_edges",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("prerequisite_id", sa.String(length=64), nullable=False),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "prerequisite_id <> concept_id", name=op.f("ck_prerequisite_edges_no_self_loop")
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name=op.f("fk_prerequisite_edges_concept_id_concepts")
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_id"],
            ["concepts.id"],
            name=op.f("fk_prerequisite_edges_prerequisite_id_concepts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prerequisite_edges")),
        sa.UniqueConstraint(
            "prerequisite_id",
            "concept_id",
            name=op.f("uq_prerequisite_edges_prerequisite_id_concept_id"),
        ),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_sessions_provenance")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'ended', 'expired')", name=op.f("ck_sessions_status")
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_sessions_revision_nonnegative")),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_sessions_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("id", "learner_id", name=op.f("uq_sessions_id_learner_id")),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_learner_id"), ["learner_id"], unique=False)

    op.create_table(
        "tutor_configurations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("appearance", sa.String(length=32), nullable=False),
        sa.Column("personality", sa.String(length=32), nullable=False),
        sa.Column("comfort_override", sa.String(length=32), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("chosen_at", sa.DateTime(), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "appearance IN ('animal', 'older_adult', 'younger_adult')",
            name=op.f("ck_tutor_configurations_appearance"),
        ),
        sa.CheckConstraint(
            "comfort_override IN ('none', 'neutral_supportive', 'reduced_sass')",
            name=op.f("ck_tutor_configurations_comfort_override"),
        ),
        sa.CheckConstraint(
            "personality IN ('gentle', 'matter_of_fact', 'playful', 'mildly_sassy')",
            name=op.f("ck_tutor_configurations_personality"),
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_tutor_configurations_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_tutor_configurations_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_configurations")),
        sa.UniqueConstraint("learner_id", name=op.f("uq_tutor_configurations_learner_id")),
    )
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("review_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "evidence_kind IN ('self_report', 'observed_work', 'inference', 'verified_assessment')",
            name=op.f("ck_memory_entries_evidence_kind"),
        ),
        sa.CheckConstraint(
            "layer IN ('episodic_note', 'session_context')", name=op.f("ck_memory_entries_layer")
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_memory_entries_provenance"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'needs_review', 'corrected', 'expired', 'deleted')",
            name=op.f("ck_memory_entries_status"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_memory_entries_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_memory_entries_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_memory_entries_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_entries")),
    )
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_memory_entries_learner_id"), ["learner_id"], unique=False
        )

    op.create_table(
        "misconception_hypotheses",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "evidence_kind = 'inference'",
            name=op.f("ck_misconception_hypotheses_evidence_kind_inference"),
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_misconception_hypotheses_provenance"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_misconception_hypotheses_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concepts.id"],
            name=op.f("fk_misconception_hypotheses_concept_id_concepts"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_misconception_hypotheses_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_misconception_hypotheses_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_misconception_hypotheses")),
    )
    with op.batch_alter_table("misconception_hypotheses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_misconception_hypotheses_learner_id"), ["learner_id"], unique=False
        )

    op.create_table(
        "observations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("concept_id", sa.String(length=64), nullable=True),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("assisted", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "correct IS NULL OR evidence_kind IN ('observed_work', 'verified_assessment')",
            name=op.f("ck_observations_correctness_needs_work"),
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('self_report', 'observed_work', 'inference', 'verified_assessment')",
            name=op.f("ck_observations_evidence_kind"),
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_observations_provenance")
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_observations_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name=op.f("fk_observations_concept_id_concepts")
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_observations_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_observations_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observations")),
    )
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_observations_learner_id"), ["learner_id"], unique=False
        )

    op.create_table(
        "problems",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("concept_id", sa.String(length=64), nullable=False),
        sa.Column("objective_id", sa.String(length=64), nullable=True),
        sa.Column("statement", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("variant_of_problem_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('practice', 'transfer', 'explanation')", name=op.f("ck_problems_kind")
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name=op.f("fk_problems_concept_id_concepts")
        ),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["learning_objectives.id"],
            name=op.f("fk_problems_objective_id_learning_objectives"),
        ),
        sa.ForeignKeyConstraint(
            ["variant_of_problem_id"],
            ["problems.id"],
            name=op.f("fk_problems_variant_of_problem_id_problems"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_problems")),
    )
    op.create_table(
        "scene_objects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("author_role", sa.String(length=16), nullable=False),
        sa.Column("semantic_role", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("teaching_step_id", sa.String(length=64), nullable=True),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "author_role IN ('student', 'tutor')", name=op.f("ck_scene_objects_author_role")
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')",
            name=op.f("ck_scene_objects_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_scene_objects_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_scene_objects_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scene_objects")),
    )
    with op.batch_alter_table("scene_objects", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_scene_objects_learner_id"), ["learner_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_scene_objects_session_id"), ["session_id"], unique=False
        )

    op.create_table(
        "attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("problem_id", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_attempts_provenance")
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_attempts_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.id"], name=op.f("fk_attempts_problem_id_problems")
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_attempts_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempts")),
        sa.UniqueConstraint("id", "learner_id", name=op.f("uq_attempts_id_learner_id")),
    )
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_attempts_learner_id"), ["learner_id"], unique=False)

    op.create_table(
        "assessments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("problem_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("assessed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('practice_check', 'transfer_check', 'explanation_check')",
            name=op.f("ck_assessments_kind"),
        ),
        sa.CheckConstraint(
            "outcome IN ('correct', 'incorrect', 'unknown')", name=op.f("ck_assessments_outcome")
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_assessments_provenance")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "learner_id"],
            ["attempts.id", "attempts.learner_id"],
            name=op.f("fk_assessments_attempt_id_learner_id_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_assessments_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.id"], name=op.f("fk_assessments_problem_id_problems")
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_assessments_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessments")),
    )
    with op.batch_alter_table("assessments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assessments_learner_id"), ["learner_id"], unique=False)

    op.create_table(
        "hints",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("concept_id", sa.String(length=64), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("answer_revealed", sa.Boolean(), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("given_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_hints_provenance")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "learner_id"],
            ["attempts.id", "attempts.learner_id"],
            name=op.f("fk_hints_attempt_id_learner_id_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name=op.f("fk_hints_concept_id_concepts")
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_hints_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_hints_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hints")),
    )
    with op.batch_alter_table("hints", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_hints_learner_id"), ["learner_id"], unique=False)

    op.create_table(
        "steps",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("input_mode", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "input_mode IN ('typed', 'confirmed_ink')", name=op.f("ck_steps_input_mode")
        ),
        sa.CheckConstraint(
            "provenance IN ('fictional_seed', 'submitted')", name=op.f("ck_steps_provenance")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "learner_id"],
            ["attempts.id", "attempts.learner_id"],
            name=op.f("fk_steps_attempt_id_learner_id_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_steps_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "learner_id"],
            ["sessions.id", "sessions.learner_id"],
            name=op.f("fk_steps_session_id_learner_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_steps")),
        sa.UniqueConstraint("attempt_id", "sequence", name=op.f("uq_steps_attempt_id_sequence")),
    )
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_steps_learner_id"), ["learner_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("steps", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_steps_learner_id"))

    op.drop_table("steps")
    with op.batch_alter_table("hints", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_hints_learner_id"))

    op.drop_table("hints")
    with op.batch_alter_table("assessments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessments_learner_id"))

    op.drop_table("assessments")
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attempts_learner_id"))

    op.drop_table("attempts")
    with op.batch_alter_table("scene_objects", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scene_objects_session_id"))
        batch_op.drop_index(batch_op.f("ix_scene_objects_learner_id"))

    op.drop_table("scene_objects")
    op.drop_table("problems")
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_observations_learner_id"))

    op.drop_table("observations")
    with op.batch_alter_table("misconception_hypotheses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_misconception_hypotheses_learner_id"))

    op.drop_table("misconception_hypotheses")
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_entries_learner_id"))

    op.drop_table("memory_entries")
    op.drop_table("tutor_configurations")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_learner_id"))

    op.drop_table("sessions")
    op.drop_table("prerequisite_edges")
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_preferences_learner_id"))

    op.drop_table("preferences")
    with op.batch_alter_table("pairing_codes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pairing_codes_learner_id"))

    op.drop_table("pairing_codes")
    with op.batch_alter_table("mastery_estimates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mastery_estimates_learner_id"))

    op.drop_table("mastery_estimates")
    op.drop_table("learning_objectives")
    with op.batch_alter_table("credentials", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_credentials_learner_id"))

    op.drop_table("credentials")
    op.drop_table("learners")
    op.drop_table("concepts")
