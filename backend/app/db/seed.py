"""Reproducible fictional seed data.

Everything here is invented demo content with ``provenance="fictional_seed"`` and fixed IDs
and timestamps, so repeated seeding is a no-op and seed history is never confused with
events actually submitted through the application.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.db.models import (
    AssessmentRow,
    AttemptRow,
    Base,
    ConceptRow,
    HintRow,
    LearnerRow,
    LearningObjectiveRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    PreferenceRow,
    PrerequisiteEdgeRow,
    ProblemRow,
    SessionRow,
    StepRow,
    TutorConfigurationRow,
)
from app.schemas import (
    Assessment,
    Attempt,
    Concept,
    ContractModel,
    Hint,
    Learner,
    LearningObjective,
    MemoryEntry,
    MisconceptionHypothesis,
    Observation,
    Preference,
    PrerequisiteEdge,
    Problem,
    Provenance,
    Session,
    Step,
    TutorConfiguration,
)

SEED_VERSION = "fictional-seed.v1"
SEED: Provenance = "fictional_seed"
_NAMESPACE = uuid.UUID("6f1d3c52-7f0e-4c43-9a55-2d8e1b7a9c10")
SEED_EPOCH = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def seed_uuid(name: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, name))


def _at(minutes: int) -> datetime:
    return SEED_EPOCH + timedelta(minutes=minutes)


DEMO_LEARNER_ADA = seed_uuid("learner:ada")
DEMO_LEARNER_BEN = seed_uuid("learner:ben")
DEMO_LEARNERS = {"ada": DEMO_LEARNER_ADA, "ben": DEMO_LEARNER_BEN}

CONCEPT_IDS = (
    "concept.multiplication",
    "concept.grouping",
    "concept.distribution",
    "concept.equality_operations",
    "concept.linear_equations",
)
FIXTURE_PROBLEM_ID = "problem.distribute_2x3_eq_14"
TRANSFER_PROBLEM_ID = "problem.transfer_3x_minus_2_eq_12"
EXPLANATION_PROBLEM_ID = "problem.explain_distribution"


def curriculum_records() -> list[ContractModel]:
    t = SEED_EPOCH - timedelta(days=30)
    concepts = [
        Concept(
            id="concept.multiplication",
            name="Multiplication",
            description="Multiplying a number by each quantity it applies to.",
            created_at=t,
        ),
        Concept(
            id="concept.grouping",
            name="Grouping with parentheses",
            description="Parentheses make several terms act as one quantity.",
            created_at=t,
        ),
        Concept(
            id="concept.distribution",
            name="Distribution",
            description="a(b + c) equals ab + ac: the outside factor multiplies every term.",
            created_at=t,
        ),
        Concept(
            id="concept.equality_operations",
            name="Equality operations",
            description="Doing the same operation to both sides keeps an equation balanced.",
            created_at=t,
        ),
        Concept(
            id="concept.linear_equations",
            name="Simple linear equations",
            description="Solving one-variable linear equations such as 2(x + 3) = 14.",
            created_at=t,
        ),
    ]
    edge_pairs = [
        ("concept.multiplication", "concept.grouping"),
        ("concept.grouping", "concept.distribution"),
        ("concept.distribution", "concept.linear_equations"),
        ("concept.equality_operations", "concept.linear_equations"),
    ]
    edges = [
        PrerequisiteEdge(
            id=f"edge.{pre.removeprefix('concept.')}__{post.removeprefix('concept.')}",
            prerequisite_id=pre,
            concept_id=post,
            created_at=t,
        )
        for pre, post in edge_pairs
    ]
    objectives = [
        LearningObjective(
            id="objective.expand_distribution",
            concept_id="concept.distribution",
            kind="procedure",
            description="Multiply the outside factor by every term inside the parentheses.",
            created_at=t,
        ),
        LearningObjective(
            id="objective.solve_linear",
            concept_id="concept.linear_equations",
            kind="procedure",
            description="Solve a simple linear equation with justified steps.",
            created_at=t,
        ),
        LearningObjective(
            id="objective.explain_distribution",
            concept_id="concept.distribution",
            kind="explanation",
            description="Explain in your own words why 2(x + 3) equals 2x + 6.",
            created_at=t,
        ),
        LearningObjective(
            id="objective.transfer_linear",
            concept_id="concept.linear_equations",
            kind="transfer",
            description="Solve a structurally different equation without help.",
            created_at=t,
        ),
    ]
    problems = [
        Problem(
            id=FIXTURE_PROBLEM_ID,
            concept_id="concept.linear_equations",
            objective_id="objective.solve_linear",
            statement="2(x + 3) = 14",
            kind="practice",
            created_at=t,
        ),
        Problem(
            id=TRANSFER_PROBLEM_ID,
            concept_id="concept.linear_equations",
            objective_id="objective.transfer_linear",
            statement="3(x - 2) = 12",
            kind="transfer",
            variant_of_problem_id=FIXTURE_PROBLEM_ID,
            created_at=t,
        ),
        Problem(
            id=EXPLANATION_PROBLEM_ID,
            concept_id="concept.distribution",
            objective_id="objective.explain_distribution",
            statement="Explain why 2(x + 3) equals 2x + 6.",
            kind="explanation",
            created_at=t,
        ),
    ]
    return [*concepts, *edges, *objectives, *problems]


def learner_records() -> list[ContractModel]:
    learners = [
        Learner(
            id=DEMO_LEARNER_ADA,
            display_name="Ada (fictional demo learner)",
            is_fictional=True,
            provenance="fictional_seed",
            created_at=_at(-60),
        ),
        Learner(
            id=DEMO_LEARNER_BEN,
            display_name="Ben (fictional demo learner)",
            is_fictional=True,
            provenance="fictional_seed",
            created_at=_at(-60),
        ),
    ]
    configs = [
        TutorConfiguration(
            id=seed_uuid("config:ada"),
            learner_id=DEMO_LEARNER_ADA,
            appearance="animal",
            personality="gentle",
            provenance="fictional_seed",
            chosen_at=_at(-59),
            last_changed_at=_at(-59),
        ),
        TutorConfiguration(
            id=seed_uuid("config:ben"),
            learner_id=DEMO_LEARNER_BEN,
            appearance="older_adult",
            personality="mildly_sassy",
            provenance="fictional_seed",
            chosen_at=_at(-59),
            last_changed_at=_at(-59),
        ),
    ]
    preferences = [
        Preference(
            id=seed_uuid("pref:ada:wait_seconds"),
            learner_id=DEMO_LEARNER_ADA,
            key="wait_seconds",
            value=20,
            provenance="fictional_seed",
            updated_at=_at(-59),
        )
    ]
    return [*learners, *configs, *preferences]


def ada_history_records() -> list[ContractModel]:
    """One earlier fictional session where Ada distributed to only the first term."""
    session_id = seed_uuid("session:ada:1")
    attempt_id = seed_uuid("attempt:ada:1")
    step_id = seed_uuid("step:ada:1:0")
    observation_id = seed_uuid("observation:ada:1:0")
    hint_id = seed_uuid("hint:ada:1:0")
    return [
        Session(
            id=session_id,
            status="ended",
            goal="Practice equations with parentheses",
            revision=4,
            started_at=_at(0),
            ended_at=_at(25),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        Attempt(
            id=attempt_id,
            session_id=session_id,
            problem_id=FIXTURE_PROBLEM_ID,
            started_at=_at(2),
            completed_at=_at(20),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        Step(
            id=step_id,
            session_id=session_id,
            attempt_id=attempt_id,
            sequence=0,
            input_mode="typed",
            content="2x + 3 = 14",
            submitted_at=_at(5),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        # Latency was not measured for this seed step, so it stays None rather than invented.
        Observation(
            id=observation_id,
            session_id=session_id,
            source_type="step",
            source_id=step_id,
            evidence_kind="observed_work",
            concept_id="concept.distribution",
            correct=False,
            latency_ms=None,
            confidence=0.9,
            assisted=False,
            observed_at=_at(5),
            recorded_at=_at(5),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        MisconceptionHypothesis(
            id=seed_uuid("hypothesis:ada:1"),
            session_id=session_id,
            concept_id="concept.distribution",
            label="Partial distribution",
            description="Multiplied only the first term inside the parentheses by 2.",
            confidence=0.55,
            alternatives=["Copying slip", "Unsure how parentheses group terms"],
            status="tentative",
            source_ids=[step_id, observation_id],
            created_at=_at(6),
            updated_at=_at(6),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        Hint(
            id=hint_id,
            session_id=session_id,
            attempt_id=attempt_id,
            concept_id="concept.distribution",
            level=1,
            answer_revealed=False,
            content="What does the 2 outside the parentheses multiply?",
            given_at=_at(7),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        Assessment(
            id=seed_uuid("assessment:ada:1"),
            session_id=session_id,
            attempt_id=attempt_id,
            problem_id=FIXTURE_PROBLEM_ID,
            kind="practice_check",
            independent=False,
            outcome="correct",
            assessed_at=_at(20),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
        MemoryEntry(
            id=seed_uuid("memory:ada:1"),
            session_id=session_id,
            layer="episodic_note",
            content="Grouping both terms helped after a hint; independent transfer not yet seen.",
            evidence_kind="observed_work",
            confidence=0.7,
            source_ids=[step_id, hint_id],
            review_at=_at(60 * 24 * 14),
            created_at=_at(25),
            updated_at=_at(25),
            learner_id=DEMO_LEARNER_ADA,
            provenance=SEED,
        ),
    ]


_ROW_FOR: dict[type[ContractModel], type[Base]] = {
    Concept: ConceptRow,
    PrerequisiteEdge: PrerequisiteEdgeRow,
    LearningObjective: LearningObjectiveRow,
    Problem: ProblemRow,
    Learner: LearnerRow,
    TutorConfiguration: TutorConfigurationRow,
    Preference: PreferenceRow,
    Session: SessionRow,
    Attempt: AttemptRow,
    Step: StepRow,
    Observation: ObservationRow,
    MisconceptionHypothesis: MisconceptionHypothesisRow,
    Hint: HintRow,
    Assessment: AssessmentRow,
    MemoryEntry: MemoryEntryRow,
}


def all_seed_records() -> list[ContractModel]:
    return [*curriculum_records(), *learner_records(), *ada_history_records()]


def insert_missing(db: DbSession, records: Sequence[ContractModel]) -> dict[str, int]:
    """Insert records whose IDs are absent; existing rows are left untouched."""
    inserted: dict[str, int] = {}
    for record in records:
        row_type = _ROW_FOR[type(record)]
        record_id = getattr(record, "id")  # noqa: B009 - every seeded contract has an id
        if db.get(row_type, record_id) is not None:
            continue
        db.add(row_type(**record.model_dump()))
        # Flush in dependency order so foreign keys are checked as each record lands.
        db.flush()
        name = row_type.__tablename__
        inserted[name] = inserted.get(name, 0) + 1
    return inserted


def seed_database(db: DbSession) -> dict[str, int]:
    return insert_missing(db, all_seed_records())
