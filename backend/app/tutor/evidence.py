"""Record student input as durable raw evidence when a turn is reserved.

Recording happens inside the short reserve transaction so a crash mid-inference never loses
a real submission, and so the fresh evidence is already visible to the bounded context built
for the provider. Check-ins become self-report observations without correctness; unconfirmed
ink is never stored as a step or assessed; tutor-authored marks create no observations here.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from app.db.models import (
    AssessmentRow,
    AttemptRow,
    EvidenceLinkRow,
    HintRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SceneObjectRow,
    StepRow,
)
from app.db.repositories import ScopedRepository
from app.learner.pairing import new_id
from app.pedagogy.policy import (
    EXPLANATION_ADEQUATE_CRITERIA,
    PARTIAL_DISTRIBUTION_ALTERNATIVES,
    PARTIAL_DISTRIBUTION_CONFIDENCE,
    PARTIAL_DISTRIBUTION_LABEL,
    WorkAnalysis,
    classify_work,
    normalize,
)
from app.pedagogy.problems import STATEMENT_X, STATEMENT_Y, ProblemSpec
from app.schemas import Assessment, EvidenceLink, MisconceptionHypothesis, Observation, Step
from app.schemas.tutor import EligibilityNote, HypothesisView, ProblemView, WorkInputMode
from app.tracing.eligibility import classify
from app.verification import DISTRIBUTION_EXPLANATION_RUBRIC, KeywordExplanationJudge
from app.verification.explanation import ExplanationJudgment
from app.whiteboard.scene import log_statement_add

_STATEMENT_NAMESPACE = uuid.UUID("5e7a9c1d-3f48-4b6a-9d2c-1a0b4e6f8c52")
# Confidence of a deterministic verifier outcome (exact) versus a rubric keyword judgment.
VERIFIED_CONFIDENCE = 1.0
OBSERVED_WORK_CONFIDENCE = 0.9
SELF_REPORT_CONFIDENCE = 0.9


def statement_object_id(session_id: str, problem_id: str) -> str:
    """Deterministic board ID for a problem statement; re-posing a problem is idempotent."""
    return str(uuid.uuid5(_STATEMENT_NAMESPACE, f"{session_id}|{problem_id}"))


def open_attempt(repo: ScopedRepository, session_id: str) -> AttemptRow | None:
    return repo.db.execute(
        select(AttemptRow)
        .where(
            AttemptRow.learner_id == repo.learner_id,
            AttemptRow.session_id == session_id,
            AttemptRow.completed_at.is_(None),
        )
        .order_by(AttemptRow.started_at.desc(), AttemptRow.id)
        .limit(1)
    ).scalar_one_or_none()


def attempt_hints(repo: ScopedRepository, attempt_id: str) -> list[HintRow]:
    return list(
        repo.db.execute(
            select(HintRow)
            .where(HintRow.learner_id == repo.learner_id, HintRow.attempt_id == attempt_id)
            .order_by(HintRow.given_at, HintRow.id)
        ).scalars()
    )


def ensure_attempt(
    repo: ScopedRepository,
    session_id: str,
    problem_id: str,
    now: datetime,
    attempt_id: str | None = None,
) -> AttemptRow:
    row = AttemptRow(
        id=attempt_id or new_id(),
        schema_version="attempt.v1",
        learner_id=repo.learner_id,
        session_id=session_id,
        problem_id=problem_id,
        provenance="submitted",
        started_at=now,
        completed_at=None,
    )
    repo.db.add(row)
    repo.db.flush()
    return row


def ensure_statement_object(
    repo: ScopedRepository, session_id: str, spec: ProblemSpec, now: datetime
) -> str:
    """The problem statement as a tutor-authored board object (created at most once)."""
    object_id = statement_object_id(session_id, spec.problem_id)
    if repo.db.get(SceneObjectRow, object_id) is None:
        repo.db.add(
            SceneObjectRow(
                id=object_id,
                schema_version="scene-object.v1",
                learner_id=repo.learner_id,
                session_id=session_id,
                author_role="tutor",
                semantic_role="problem_statement",
                kind="text",
                payload={
                    "text": spec.statement,
                    "x": STATEMENT_X,
                    "y": STATEMENT_Y,
                    "color_role": "tutor",
                },
                teaching_step_id=None,
                provenance="submitted",
                created_at=now,
                deleted_at=None,
            )
        )
        log_statement_add(repo, session_id, spec.problem_id, object_id, now)
        repo.db.flush()
    return object_id


def problem_view(spec: ProblemSpec, attempt_id: str, statement_id: str | None) -> ProblemView:
    return ProblemView(
        problem_id=spec.problem_id,
        attempt_id=attempt_id,
        statement=spec.statement,
        kind=spec.kind,
        concept_id=spec.concept_id,
        statement_object_id=statement_id,
    )


def _eligibility_note(
    observation: ObservationRow,
    assessment: AssessmentRow | None,
    hints: list[HintRow],
) -> EligibilityNote:
    event = classify(observation, assessment, hints)
    return EligibilityNote(
        observation_id=observation.id,
        evidence_kind=observation.evidence_kind,
        source_type=observation.source_type,
        assisted=observation.assisted,
        eligible=event.eligible,
        reason=event.ineligible_reason,
        update_status=None,
    )


def record_check_in(
    repo: ScopedRepository, session_id: str, turn_id: str, now: datetime
) -> tuple[str, EligibilityNote]:
    """A check-in is a self-report observation: no concept, no correctness, never BKT input."""
    row = ObservationRow(
        **Observation(
            id=new_id(),
            learner_id=repo.learner_id,
            session_id=session_id,
            source_type="check_in",
            source_id=turn_id,
            evidence_kind="self_report",
            concept_id=None,
            correct=None,
            latency_ms=None,
            confidence=SELF_REPORT_CONFIDENCE,
            assisted=False,
            provenance="submitted",
            observed_at=now,
            recorded_at=now,
        ).model_dump()
    )
    repo.db.add(row)
    repo.db.flush()
    return row.id, _eligibility_note(row, None, [])


@dataclass(frozen=True)
class RecordedWork:
    """Raw evidence created for one work submission, plus everything the policy needs."""

    analysis: WorkAnalysis
    step_id: str | None
    observation_ids: tuple[str, ...]
    assessment_id: str | None
    assessment_kind: str | None
    assessment_independent: bool | None
    assessment_observation_id: str | None
    hypothesis: HypothesisView | None
    explanation: ExplanationJudgment | None
    explanation_missing: str | None
    eligibility: tuple[EligibilityNote, ...]
    attempt_hint_ids: tuple[str, ...]
    attempt_hint_levels: tuple[int, ...]
    expanded_seen: bool


def _partial_distribution_hypothesis(
    repo: ScopedRepository,
    session_id: str,
    spec: ProblemSpec,
    step_id: str,
    observation_id: str,
    now: datetime,
) -> HypothesisView:
    """Find or create the tentative partial-distribution hypothesis and link this observation.

    One matching step is weak evidence: the hypothesis stays tentative, keeps its
    alternatives, and the new observation joins it through a personal evidence link.
    """
    row = repo.db.execute(
        select(MisconceptionHypothesisRow)
        .where(
            MisconceptionHypothesisRow.learner_id == repo.learner_id,
            MisconceptionHypothesisRow.concept_id == spec.step_concept_id,
            MisconceptionHypothesisRow.label == PARTIAL_DISTRIBUTION_LABEL,
            MisconceptionHypothesisRow.status != "retracted",
        )
        .order_by(MisconceptionHypothesisRow.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        hypothesis = MisconceptionHypothesis(
            id=new_id(),
            learner_id=repo.learner_id,
            session_id=session_id,
            concept_id=spec.step_concept_id,
            label=PARTIAL_DISTRIBUTION_LABEL,
            description=(
                "Multiplied only the first term inside the parentheses by the outside factor."
            ),
            confidence=PARTIAL_DISTRIBUTION_CONFIDENCE,
            alternatives=list(PARTIAL_DISTRIBUTION_ALTERNATIVES),
            status="tentative",
            source_ids=[step_id, observation_id],
            provenance="submitted",
            created_at=now,
            updated_at=now,
        )
        repo.db.add(MisconceptionHypothesisRow(**hypothesis.model_dump()))
    else:
        hypothesis = MisconceptionHypothesis.model_validate(row)
    repo.db.flush()
    linked = repo.db.execute(
        select(EvidenceLinkRow.id).where(
            EvidenceLinkRow.hypothesis_id == hypothesis.id,
            EvidenceLinkRow.observation_id == observation_id,
        )
    ).scalar_one_or_none()
    if linked is None:
        repo.db.add(
            EvidenceLinkRow(
                **EvidenceLink(
                    id=new_id(),
                    learner_id=repo.learner_id,
                    hypothesis_id=hypothesis.id,
                    observation_id=observation_id,
                    polarity="supports",
                    strength=0.6,
                    rationale="Multiplied only the first term inside the parentheses.",
                    provenance="submitted",
                    created_at=now,
                ).model_dump()
            )
        )
        repo.db.flush()
    return HypothesisView(
        id=hypothesis.id,
        label=hypothesis.label,
        confidence=hypothesis.confidence,
        alternatives=list(hypothesis.alternatives),
        status=hypothesis.status,
        source_ids=list(hypothesis.source_ids),
    )


_SOLUTION_KINDS = ("solution_with_reasoning", "solution_without_reasoning", "wrong_solution")


def record_work(
    repo: ScopedRepository,
    session_id: str,
    attempt: AttemptRow,
    spec: ProblemSpec,
    text: str,
    input_mode: WorkInputMode,
    now: datetime,
) -> RecordedWork:
    """Verify and store one submission. Returns the raw records and policy facts."""
    prior_steps = list(
        repo.db.execute(
            select(StepRow)
            .where(StepRow.attempt_id == attempt.id, StepRow.learner_id == repo.learner_id)
            .order_by(StepRow.sequence)
        ).scalars()
    )
    hints = attempt_hints(repo, attempt.id)
    hint_ids = tuple(h.id for h in hints)
    hint_levels = tuple(h.level for h in hints)
    assisted = bool(hints)
    expanded_seen = spec.expanded_step is not None and any(
        normalize(step.content) == normalize(spec.expanded_step) for step in prior_steps
    )
    analysis = classify_work(spec, [step.content for step in prior_steps], text, input_mode)
    if input_mode == "unconfirmed_ink":
        # Raw ink is never stored as a step and never assessed; the tutor asks to confirm.
        return RecordedWork(
            analysis=analysis,
            step_id=None,
            observation_ids=(),
            assessment_id=None,
            assessment_kind=None,
            assessment_independent=None,
            assessment_observation_id=None,
            hypothesis=None,
            explanation=None,
            explanation_missing=None,
            eligibility=(),
            attempt_hint_ids=hint_ids,
            attempt_hint_levels=hint_levels,
            expanded_seen=expanded_seen,
        )

    step_row = StepRow(
        **Step(
            id=new_id(),
            learner_id=repo.learner_id,
            session_id=session_id,
            attempt_id=attempt.id,
            sequence=len(prior_steps),
            input_mode="confirmed_ink" if input_mode == "confirmed_ink" else "typed",
            content=text,
            provenance="submitted",
            submitted_at=now,
        ).model_dump()
    )
    repo.db.add(step_row)
    repo.db.flush()

    classification = analysis.classification
    assessment_row: AssessmentRow | None = None
    assessment_observation_id: str | None = None
    explanation: ExplanationJudgment | None = None
    explanation_missing: str | None = None
    observation_rows: list[ObservationRow] = []

    if classification == "explanation":
        explanation = KeywordExplanationJudge().judge(DISTRIBUTION_EXPLANATION_RUBRIC, text)
        met = [j.criterion_id for j in explanation.judgments if j.status == "met"]
        adequate = len(met) >= EXPLANATION_ADEQUATE_CRITERIA
        explanation_missing = next(
            (c.id for c in DISTRIBUTION_EXPLANATION_RUBRIC.criteria if c.id not in met), None
        )
        assessment_row = AssessmentRow(
            **Assessment(
                id=new_id(),
                learner_id=repo.learner_id,
                session_id=session_id,
                attempt_id=attempt.id,
                problem_id=spec.problem_id,
                kind="explanation_check",
                independent=True,
                outcome="correct" if adequate else "unknown",
                provenance="submitted",
                assessed_at=now,
            ).model_dump()
        )
        repo.db.add(assessment_row)
        repo.db.flush()
        # A rubric judgment is a bounded inference, so confidence stays at the rubric cap and
        # an incomplete explanation keeps correctness unmeasured rather than "wrong".
        observation_rows.append(
            ObservationRow(
                **Observation(
                    id=new_id(),
                    learner_id=repo.learner_id,
                    session_id=session_id,
                    source_type="assessment",
                    source_id=assessment_row.id,
                    evidence_kind="verified_assessment",
                    concept_id=spec.concept_id,
                    correct=True if adequate else None,
                    latency_ms=None,
                    confidence=DISTRIBUTION_EXPLANATION_RUBRIC.max_confidence,
                    assisted=False,
                    provenance="submitted",
                    observed_at=now,
                    recorded_at=now,
                ).model_dump()
            )
        )
    elif classification in _SOLUTION_KINDS:
        outcome: Literal["correct", "incorrect"] = (
            "incorrect" if classification == "wrong_solution" else "correct"
        )
        assessment_row = AssessmentRow(
            **Assessment(
                id=new_id(),
                learner_id=repo.learner_id,
                session_id=session_id,
                attempt_id=attempt.id,
                problem_id=spec.problem_id,
                kind="practice_check" if spec.kind == "practice" else "transfer_check",
                # Hints earlier in this attempt make the outcome assisted, and a correct
                # value without verified reasoning is not independent evidence either.
                independent=not assisted and classification != "solution_without_reasoning",
                outcome=outcome,
                provenance="submitted",
                assessed_at=now,
            ).model_dump()
        )
        repo.db.add(assessment_row)
        repo.db.flush()
        assessment_observation_id = new_id()
        observation_rows.append(
            ObservationRow(
                **Observation(
                    id=assessment_observation_id,
                    learner_id=repo.learner_id,
                    session_id=session_id,
                    source_type="assessment",
                    source_id=assessment_row.id,
                    evidence_kind="verified_assessment",
                    concept_id=spec.concept_id,
                    correct=outcome == "correct",
                    latency_ms=None,
                    confidence=VERIFIED_CONFIDENCE,
                    assisted=assisted,
                    provenance="submitted",
                    observed_at=now,
                    recorded_at=now,
                ).model_dump()
            )
        )
    else:
        status = analysis.verification.status if analysis.verification is not None else "unknown"
        observation_rows.append(
            ObservationRow(
                **Observation(
                    id=new_id(),
                    learner_id=repo.learner_id,
                    session_id=session_id,
                    source_type="step",
                    source_id=step_row.id,
                    evidence_kind="observed_work",
                    concept_id=spec.step_concept_id,
                    correct={"valid": True, "invalid": False}.get(status),
                    latency_ms=None,
                    confidence=OBSERVED_WORK_CONFIDENCE,
                    assisted=assisted,
                    provenance="submitted",
                    observed_at=now,
                    recorded_at=now,
                ).model_dump()
            )
        )
    for observation_row in observation_rows:
        repo.db.add(observation_row)
    repo.db.flush()

    hypothesis = None
    if classification == "partial_distribution":
        hypothesis = _partial_distribution_hypothesis(
            repo, session_id, spec, step_row.id, observation_rows[0].id, now
        )
    eligibility = tuple(
        _eligibility_note(observation_row, assessment_row, hints)
        for observation_row in observation_rows
    )
    return RecordedWork(
        analysis=analysis,
        step_id=step_row.id,
        observation_ids=tuple(row.id for row in observation_rows),
        assessment_id=None if assessment_row is None else assessment_row.id,
        assessment_kind=None if assessment_row is None else assessment_row.kind,
        assessment_independent=None if assessment_row is None else assessment_row.independent,
        assessment_observation_id=assessment_observation_id,
        hypothesis=hypothesis,
        explanation=explanation,
        explanation_missing=explanation_missing,
        eligibility=eligibility,
        attempt_hint_ids=hint_ids,
        attempt_hint_levels=hint_levels,
        expanded_seen=expanded_seen,
    )
