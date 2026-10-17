"""Relational tables for learner evidence, curriculum, sessions, configuration and scenes.

Column names match the Pydantic contracts in ``app.schemas`` so rows validate directly with
``Contract.model_validate(row)``. Learner-owned child rows reference their parent through
composite ``(id, learner_id)`` foreign keys, so the database itself refuses a record that
points at another learner's session or attempt.
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime
from app.schemas.common import EVIDENCE_KIND_VALUES, PROVENANCE_VALUES
from app.schemas.graph import EVIDENCE_POLARITY_VALUES

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ID = String(64)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: UTCDateTime()}


def _one_of(name: str, column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def _provenance() -> CheckConstraint:
    return _one_of("provenance", "provenance", PROVENANCE_VALUES)


def _evidence_kind() -> CheckConstraint:
    return _one_of("evidence_kind", "evidence_kind", EVIDENCE_KIND_VALUES)


def _confidence(column: str = "confidence") -> CheckConstraint:
    return CheckConstraint(f"{column} >= 0 AND {column} <= 1", name=f"{column}_range")


def _session_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["session_id", "learner_id"],
        ["sessions.id", "sessions.learner_id"],
        ondelete="CASCADE",
    )


def _attempt_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["attempt_id", "learner_id"],
        ["attempts.id", "attempts.learner_id"],
        ondelete="CASCADE",
    )


def _learner_fk() -> Any:
    return ForeignKey("learners.id", ondelete="CASCADE")


class LearnerRow(Base):
    __tablename__ = "learners"
    __table_args__ = (_provenance(),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(80))
    is_fictional: Mapped[bool] = mapped_column(Boolean)
    provenance: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime]


class CredentialRow(Base):
    """A paired device credential. Only the SHA-256 digest of the bearer token is stored."""

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class PairingCodeRow(Base):
    """A short-lived, one-time code issued locally by the admin CLI."""

    __tablename__ = "pairing_codes"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    redeemed_at: Mapped[datetime | None]


class ConceptRow(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime]


class PrerequisiteEdgeRow(Base):
    __tablename__ = "prerequisite_edges"
    __table_args__ = (
        UniqueConstraint("prerequisite_id", "concept_id"),
        CheckConstraint("prerequisite_id <> concept_id", name="no_self_loop"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    prerequisite_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    concept_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    created_at: Mapped[datetime]


class LearningObjectiveRow(Base):
    __tablename__ = "learning_objectives"
    __table_args__ = (_one_of("kind", "kind", ("procedure", "explanation", "transfer")),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    concept_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    kind: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime]


class ProblemRow(Base):
    __tablename__ = "problems"
    __table_args__ = (_one_of("kind", "kind", ("practice", "transfer", "explanation")),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    concept_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    objective_id: Mapped[str | None] = mapped_column(ID, ForeignKey("learning_objectives.id"))
    statement: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    variant_of_problem_id: Mapped[str | None] = mapped_column(ID, ForeignKey("problems.id"))
    created_at: Mapped[datetime]


class SessionRow(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("id", "learner_id"),
        _provenance(),
        _one_of("status", "status", ("active", "ended", "expired")),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    status: Mapped[str] = mapped_column(String(16))
    goal: Mapped[str | None] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    # Monotonic scene counter, separate from the tutor-turn revision: board edits and
    # tutor turns are independent command streams with their own optimistic-concurrency CAS.
    scene_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    provenance: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]


class AttemptRow(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("id", "learner_id"), _session_fk(), _provenance())

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str] = mapped_column(ID)
    problem_id: Mapped[str] = mapped_column(ID, ForeignKey("problems.id"))
    provenance: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]


class StepRow(Base):
    __tablename__ = "steps"
    __table_args__ = (
        UniqueConstraint("attempt_id", "sequence"),
        _session_fk(),
        _attempt_fk(),
        _provenance(),
        _one_of("input_mode", "input_mode", ("typed", "confirmed_ink")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str] = mapped_column(ID)
    attempt_id: Mapped[str] = mapped_column(ID)
    sequence: Mapped[int] = mapped_column(Integer)
    input_mode: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String(500))
    provenance: Mapped[str] = mapped_column(String(32))
    submitted_at: Mapped[datetime]


class ObservationRow(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("id", "learner_id"),
        _session_fk(),
        _provenance(),
        _evidence_kind(),
        _confidence(),
        CheckConstraint(
            "correct IS NULL OR evidence_kind IN ('observed_work', 'verified_assessment')",
            name="correctness_needs_work",
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str | None] = mapped_column(ID)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(ID)
    evidence_kind: Mapped[str] = mapped_column(String(32))
    concept_id: Mapped[str | None] = mapped_column(ID, ForeignKey("concepts.id"))
    correct: Mapped[bool | None] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    assisted: Mapped[bool] = mapped_column(Boolean)
    provenance: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime]
    recorded_at: Mapped[datetime]


class HintRow(Base):
    __tablename__ = "hints"
    __table_args__ = (_session_fk(), _attempt_fk(), _provenance())

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str] = mapped_column(ID)
    attempt_id: Mapped[str | None] = mapped_column(ID)
    concept_id: Mapped[str | None] = mapped_column(ID, ForeignKey("concepts.id"))
    level: Mapped[int] = mapped_column(Integer)
    answer_revealed: Mapped[bool] = mapped_column(Boolean)
    content: Mapped[str] = mapped_column(String(500))
    provenance: Mapped[str] = mapped_column(String(32))
    given_at: Mapped[datetime]


class AssessmentRow(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        _session_fk(),
        _attempt_fk(),
        _provenance(),
        _one_of("kind", "kind", ("practice_check", "transfer_check", "explanation_check")),
        _one_of("outcome", "outcome", ("correct", "incorrect", "unknown")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str] = mapped_column(ID)
    attempt_id: Mapped[str] = mapped_column(ID)
    problem_id: Mapped[str] = mapped_column(ID, ForeignKey("problems.id"))
    kind: Mapped[str] = mapped_column(String(32))
    independent: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str] = mapped_column(String(16))
    provenance: Mapped[str] = mapped_column(String(32))
    assessed_at: Mapped[datetime]


class MisconceptionHypothesisRow(Base):
    __tablename__ = "misconception_hypotheses"
    __table_args__ = (
        UniqueConstraint("id", "learner_id"),
        _session_fk(),
        _provenance(),
        _confidence(),
        CheckConstraint("evidence_kind = 'inference'", name="evidence_kind_inference"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str | None] = mapped_column(ID)
    concept_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500))
    confidence: Mapped[float] = mapped_column(Float)
    alternatives: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    evidence_kind: Mapped[str] = mapped_column(String(32))
    source_ids: Mapped[list[str]] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class EvidenceLinkRow(Base):
    """Personal evidence: an observation supporting or contradicting a hypothesis.

    Stored apart from ``prerequisite_edges``; it has no concept-to-concept columns at all.
    """

    __tablename__ = "evidence_links"
    __table_args__ = (
        UniqueConstraint("hypothesis_id", "observation_id"),
        ForeignKeyConstraint(
            ["hypothesis_id", "learner_id"],
            ["misconception_hypotheses.id", "misconception_hypotheses.learner_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["observation_id", "learner_id"],
            ["observations.id", "observations.learner_id"],
            ondelete="CASCADE",
        ),
        _provenance(),
        _one_of("polarity", "polarity", EVIDENCE_POLARITY_VALUES),
        _confidence("strength"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    hypothesis_id: Mapped[str] = mapped_column(ID)
    observation_id: Mapped[str] = mapped_column(ID)
    polarity: Mapped[str] = mapped_column(String(16))
    strength: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(String(200))
    provenance: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime]


class MasteryEstimateRow(Base):
    __tablename__ = "mastery_estimates"
    __table_args__ = (_provenance(), _confidence("p_known"))

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    concept_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    algorithm: Mapped[str] = mapped_column(String(40))
    algorithm_version: Mapped[str] = mapped_column(String(40))
    parameter_version: Mapped[str] = mapped_column(String(40))
    p_known: Mapped[float] = mapped_column(Float)
    calibrated: Mapped[bool] = mapped_column(Boolean)
    source_observation_ids: Mapped[list[str]] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(32))
    computed_at: Mapped[datetime]


class BKTParameterSetRow(Base):
    """An immutable, versioned BKT parameter set. Hand-set rows are never calibrated."""

    __tablename__ = "bkt_parameter_sets"
    __table_args__ = (
        _confidence("p_init"),
        _confidence("p_learn"),
        _confidence("p_guess"),
        _confidence("p_slip"),
        CheckConstraint("p_guess + p_slip < 1", name="identifiable"),
        _one_of("source", "source", ("hand_set", "fitted")),
        CheckConstraint("calibrated = 0 OR source = 'fitted'", name="calibrated_needs_fit"),
    )

    parameter_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    p_init: Mapped[float] = mapped_column(Float)
    p_learn: Mapped[float] = mapped_column(Float)
    p_guess: Mapped[float] = mapped_column(Float)
    p_slip: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))
    calibrated: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime]


class BKTCountedOpportunityRow(Base):
    """Derived ledger: one row per counted independent opportunity per parameter version.

    Rows are rebuilt from raw observations on every replay. The unique constraints make a
    duplicated opportunity or observation within one parameter version impossible.
    """

    __tablename__ = "bkt_counted_opportunities"
    __table_args__ = (
        UniqueConstraint("learner_id", "parameter_version", "concept_id", "opportunity_key"),
        UniqueConstraint("learner_id", "parameter_version", "observation_id"),
        ForeignKeyConstraint(
            ["observation_id", "learner_id"],
            ["observations.id", "observations.learner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        _confidence("p_known_before"),
        _confidence("p_correct_predicted"),
        _confidence("p_known_posterior"),
        _confidence("p_known_after"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    concept_id: Mapped[str] = mapped_column(ID, ForeignKey("concepts.id"))
    parameter_version: Mapped[str] = mapped_column(
        String(40), ForeignKey("bkt_parameter_sets.parameter_version")
    )
    algorithm_version: Mapped[str] = mapped_column(String(40))
    eligibility_version: Mapped[str] = mapped_column(String(40))
    observation_id: Mapped[str] = mapped_column(ID)
    opportunity_key: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column(Integer)
    p_known_before: Mapped[float] = mapped_column(Float)
    p_correct_predicted: Mapped[float] = mapped_column(Float)
    observed_correct: Mapped[bool] = mapped_column(Boolean)
    p_known_posterior: Mapped[float] = mapped_column(Float)
    p_known_after: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime]


class PreferenceRow(Base):
    __tablename__ = "preferences"
    __table_args__ = (UniqueConstraint("learner_id", "key"), _provenance())

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    provenance: Mapped[str] = mapped_column(String(32))
    updated_by: Mapped[str] = mapped_column(String(16), server_default="learner")
    updated_at: Mapped[datetime]


class TutorConfigurationRow(Base):
    __tablename__ = "tutor_configurations"
    __table_args__ = (
        _provenance(),
        _one_of("appearance", "appearance", ("animal", "older_adult", "younger_adult")),
        _one_of(
            "personality",
            "personality",
            ("gentle", "matter_of_fact", "playful", "mildly_sassy"),
        ),
        _one_of(
            "comfort_override",
            "comfort_override",
            ("none", "neutral_supportive", "reduced_sass"),
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), unique=True)
    appearance: Mapped[str] = mapped_column(String(32))
    personality: Mapped[str] = mapped_column(String(32))
    comfort_override: Mapped[str] = mapped_column(String(32))
    provenance: Mapped[str] = mapped_column(String(32))
    chosen_at: Mapped[datetime]
    last_changed_at: Mapped[datetime]
    comfort_updated_at: Mapped[datetime | None]


class MemoryEntryRow(Base):
    __tablename__ = "memory_entries"
    __table_args__ = (
        _session_fk(),
        _provenance(),
        _evidence_kind(),
        _confidence(),
        _one_of("layer", "layer", ("episodic_note", "session_context")),
        _one_of("status", "status", ("active", "needs_review", "corrected", "expired", "deleted")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str | None] = mapped_column(ID)
    layer: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(String(500))
    evidence_kind: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    source_ids: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    review_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    origin: Mapped[str] = mapped_column(String(16), server_default="system")
    turn_id: Mapped[str | None] = mapped_column(ID)
    supersedes_id: Mapped[str | None] = mapped_column(ID)
    provenance: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class SceneObjectRow(Base):
    __tablename__ = "scene_objects"
    __table_args__ = (
        _session_fk(),
        _provenance(),
        _one_of("author_role", "author_role", ("student", "tutor")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str] = mapped_column(ID, index=True)
    author_role: Mapped[str] = mapped_column(String(16))
    semantic_role: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    teaching_step_id: Mapped[str | None] = mapped_column(ID)
    provenance: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime]
    deleted_at: Mapped[datetime | None]


class SceneOperationRow(Base):
    """One committed scene operation in a session's durable, append-only operation log.

    Every visible board change (student strokes, erases, history moves and tutor teaching
    moves) is one row with a monotonic per-session ``seq`` equal to the scene revision it
    produced. The log is the authoritative history; ``scene_objects.deleted_at`` is the
    materialized visibility maintained in the same transaction. Undo/redo rows reference
    the operations they reverse or reapply, so a reload replays edits exactly instead of
    resurrecting erased or undone objects.
    """

    __tablename__ = "scene_operations"
    __table_args__ = (
        # The operation id is client-chosen for student commands, so uniqueness is scoped
        # per learner: another learner's ids can never collide with or replay these.
        PrimaryKeyConstraint("learner_id", "id"),
        UniqueConstraint("learner_id", "session_id", "seq"),
        _session_fk(),
        _one_of("author_role", "author_role", ("student", "tutor")),
        _one_of(
            "kind",
            "kind",
            ("add_object", "erase_object", "undo", "redo", "undo_tutor_move"),
        ),
        CheckConstraint("seq >= 1", name="seq_positive"),
    )

    learner_id: Mapped[str] = mapped_column(ID, index=True)
    id: Mapped[str] = mapped_column(ID)
    schema_version: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(ID, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    author_role: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(24))
    # The object this op created/erased (add/erase) or most directly affected (undo/redo).
    object_id: Mapped[str | None] = mapped_column(ID)
    # The teaching move (tutor turn id) this op belongs to or, for undo_tutor_move, undoes.
    move_id: Mapped[str | None] = mapped_column(ID)
    # For undo: the op it reverses. For redo: the op it reapplies.
    reverses_op_id: Mapped[str | None] = mapped_column(ID)
    # For redo: the undo op it consumes.
    consumes_op_id: Mapped[str | None] = mapped_column(ID)
    affected_object_ids: Mapped[list[str]] = mapped_column(JSON)
    # Hash of the canonical request, so a reused operation id with different content
    # conflicts instead of silently replaying a different edit.
    request_hash: Mapped[str] = mapped_column(String(64))
    # The undo op currently reversing this op (NULL while the op is in effect).
    reversed_by: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime]


class TutorTurnRow(Base):
    """One reserved tutor turn: idempotency key, revisions, the deterministic plan and result.

    A turn is reserved (``pending``) in a short transaction, inference runs outside any
    transaction, and the turn is then finished as ``committed``, ``rejected``, ``failed`` or
    ``superseded``. ``(learner_id, idempotency_key)`` is unique so a retried command can
    never reserve a second turn.
    """

    __tablename__ = "tutor_turns"
    __table_args__ = (
        UniqueConstraint("learner_id", "idempotency_key"),
        _session_fk(),
        _one_of("kind", "kind", ("check_in", "work")),
        _one_of("status", "status", ("pending", "committed", "rejected", "failed", "superseded")),
        CheckConstraint("base_revision >= 0", name="base_revision_nonnegative"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    session_id: Mapped[str] = mapped_column(ID, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    base_revision: Mapped[int] = mapped_column(Integer)
    committed_revision: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(40))
    is_mock: Mapped[bool] = mapped_column(Boolean)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]


class SessionWaitSignalRow(Base):
    """The learner's explicit "Still thinking" presses for one session.

    This is a record of a deliberate request for space, not an observation: it never feeds
    correctness, latency or mastery. One row per session keeps repeated presses bounded.
    """

    __tablename__ = "session_wait_signals"
    __table_args__ = (
        PrimaryKeyConstraint("learner_id", "session_id"),
        _session_fk(),
        CheckConstraint("still_thinking_count >= 0", name="still_thinking_count_nonnegative"),
    )

    learner_id: Mapped[str] = mapped_column(ID)
    session_id: Mapped[str] = mapped_column(ID)
    still_thinking_at: Mapped[datetime | None]
    still_thinking_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime]


class EvidenceCorrectionRow(Base):
    """A learner's correction of one observation's correctness, with the original preserved.

    The observation (and its assessment) carries the *current* value so every reader sees
    one truth; this row keeps what the system originally recorded and when the learner
    changed it, so the correction stays distinguishable from measured evidence.
    """

    __tablename__ = "evidence_corrections"
    __table_args__ = (
        UniqueConstraint("learner_id", "observation_id"),
        ForeignKeyConstraint(
            ["observation_id", "learner_id"],
            ["observations.id", "observations.learner_id"],
            ondelete="CASCADE",
        ),
        _provenance(),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, _learner_fk(), index=True)
    observation_id: Mapped[str] = mapped_column(ID)
    original_correct: Mapped[bool] = mapped_column(Boolean)
    corrected_correct: Mapped[bool] = mapped_column(Boolean)
    original_assessment_outcome: Mapped[str | None] = mapped_column(String(16))
    provenance: Mapped[str] = mapped_column(String(32))
    corrected_at: Mapped[datetime]


class DeletionTombstoneRow(Base):
    """Marks a removed record ID so reseeding or replay cannot resurrect it.

    Deliberately holds no content and has no foreign key to the learner, so it survives
    profile deletion. It never stores text from the deleted record.
    """

    __tablename__ = "deletion_tombstones"
    __table_args__ = (
        UniqueConstraint("learner_id", "record_id"),
        _one_of(
            "reason",
            "reason",
            ("learner_deleted", "source_deleted", "session_deleted", "profile_deleted"),
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    learner_id: Mapped[str] = mapped_column(ID, index=True)
    record_kind: Mapped[str] = mapped_column(String(32))
    record_id: Mapped[str] = mapped_column(ID, index=True)
    reason: Mapped[str] = mapped_column(String(24))
    deleted_at: Mapped[datetime]
