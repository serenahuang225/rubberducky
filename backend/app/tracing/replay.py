"""Deterministic replay of raw evidence into BKT estimates, with versioned persistence.

Replay always starts from ``p_init`` and walks a learner's raw observations in a fixed order
(``observed_at``, ``recorded_at``, ``id``). Derived rows for that learner and parameter
version are then replaced as a whole, so repeating a replay, or replaying after a restart,
yields the same estimates and counts without duplicating anything. A new parameter version
is recomputed from raw history; an old posterior is never fed back in as an observation.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.db.models import (
    AssessmentRow,
    BKTCountedOpportunityRow,
    BKTParameterSetRow,
    HintRow,
    MasteryEstimateRow,
    ObservationRow,
)
from app.schemas import MasteryEstimate
from app.tracing.contracts import (
    ALGORITHM,
    ALGORITHM_VERSION,
    DEFAULT_PARAMETERS,
    ELIGIBILITY_VERSION,
    BKTParameters,
    ConceptEstimate,
    CountedOpportunity,
    PersistedTracing,
    ReplayReport,
    TracingEvent,
    TracingUpdate,
)
from app.tracing.eligibility import classify
from app.tracing.predictor import BKTPredictor

_NAMESPACE = uuid.UUID("0b8e6f0e-3d0a-4b9e-9a51-6c1f7d3e2a40")
# MasteryEstimate keeps a bounded source list; the full ledger is bkt_counted_opportunities.
MAX_ESTIMATE_SOURCES = 20


class UnknownParameterVersionError(LookupError):
    pass


class ParameterConflictError(ValueError):
    """A parameter version already exists with different values; versions are immutable."""


def derived_id(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "|".join(parts)))


def load_events(db: DbSession, learner_id: str) -> list[TracingEvent]:
    observations = db.execute(
        select(ObservationRow)
        .where(ObservationRow.learner_id == learner_id)
        .order_by(ObservationRow.observed_at, ObservationRow.recorded_at, ObservationRow.id)
    ).scalars()
    assessments = {
        row.id: row
        for row in db.execute(
            select(AssessmentRow).where(AssessmentRow.learner_id == learner_id)
        ).scalars()
    }
    hints_by_attempt: dict[str, list[HintRow]] = defaultdict(list)
    for hint in db.execute(select(HintRow).where(HintRow.learner_id == learner_id)).scalars():
        if hint.attempt_id is not None:
            hints_by_attempt[hint.attempt_id].append(hint)
    events = []
    for observation in observations:
        assessment = (
            assessments.get(observation.source_id)
            if observation.source_type == "assessment"
            else None
        )
        hints = hints_by_attempt.get(assessment.attempt_id, []) if assessment else []
        events.append(classify(observation, assessment, hints))
    return events


def replay_events(
    learner_id: str, events: list[TracingEvent], parameters: BKTParameters
) -> tuple[BKTPredictor, ReplayReport]:
    predictor = BKTPredictor(learner_id, parameters)
    updates: list[TracingUpdate] = [predictor.observe(event) for event in events]
    estimates = [
        ConceptEstimate(
            concept_id=concept_id,
            p_known=predictor.p_known(concept_id),
            counted_opportunities=len(predictor.counted_opportunities(concept_id)),
            source_observation_ids=predictor.source_observation_ids(concept_id),
        )
        for concept_id in predictor.concepts()
    ]
    report = ReplayReport(
        learner_id=learner_id,
        metadata=predictor.metadata(),
        parameters=parameters,
        raw_event_ids=[event.observation_id for event in events],
        updates=updates,
        estimates=estimates,
        counted_opportunities=sum(e.counted_opportunities for e in estimates),
    )
    return predictor, report


def _to_contract(row: BKTParameterSetRow) -> BKTParameters:
    return BKTParameters.model_validate(row)


def list_parameters(db: DbSession) -> list[BKTParameters]:
    rows = db.execute(
        select(BKTParameterSetRow).order_by(BKTParameterSetRow.parameter_version)
    ).scalars()
    return [_to_contract(row) for row in rows]


def register_parameters(db: DbSession, parameters: BKTParameters, now: datetime) -> bool:
    """Store a parameter set; returns False if an identical one already exists."""
    existing = db.get(BKTParameterSetRow, parameters.parameter_version)
    if existing is not None:
        if _to_contract(existing) != parameters:
            raise ParameterConflictError(
                f"parameter version {parameters.parameter_version} already exists with "
                "different values; register a new version instead"
            )
        return False
    db.add(BKTParameterSetRow(**parameters.model_dump(), created_at=now))
    db.flush()
    return True


def get_parameters(db: DbSession, parameter_version: str, now: datetime) -> BKTParameters:
    if parameter_version == DEFAULT_PARAMETERS.parameter_version:
        register_parameters(db, DEFAULT_PARAMETERS, now)
    row = db.get(BKTParameterSetRow, parameter_version)
    if row is None:
        raise UnknownParameterVersionError(parameter_version)
    return _to_contract(row)


def _estimate_provenance(events: list[TracingEvent], source_ids: set[str]) -> str:
    sources = [event for event in events if event.observation_id in source_ids]
    return (
        "fictional_seed"
        if all(e.provenance == "fictional_seed" for e in sources)
        else ("submitted")
    )


def _persist(
    db: DbSession, report: ReplayReport, events: list[TracingEvent], now: datetime
) -> None:
    learner_id = report.learner_id
    version = report.parameters.parameter_version
    db.execute(
        delete(BKTCountedOpportunityRow).where(
            BKTCountedOpportunityRow.learner_id == learner_id,
            BKTCountedOpportunityRow.parameter_version == version,
        )
    )
    db.execute(
        delete(MasteryEstimateRow).where(
            MasteryEstimateRow.learner_id == learner_id,
            MasteryEstimateRow.algorithm == ALGORITHM,
            MasteryEstimateRow.parameter_version == version,
        )
    )
    for update in report.updates:
        if update.status != "counted" or update.prediction is None:
            continue
        counted = CountedOpportunity.model_validate(
            {
                "id": derived_id("bkt-opportunity", learner_id, version, update.observation_id),
                "learner_id": learner_id,
                "concept_id": update.concept_id,
                "parameter_version": version,
                "algorithm_version": ALGORITHM_VERSION,
                "eligibility_version": ELIGIBILITY_VERSION,
                "observation_id": update.observation_id,
                "opportunity_key": update.opportunity_key,
                "sequence": update.sequence,
                "p_known_before": update.prediction.latent_knowledge,
                "p_correct_predicted": update.prediction.p_correct,
                "observed_correct": update.observed_correct,
                "p_known_posterior": update.p_known_posterior,
                "p_known_after": update.p_known_after,
                "computed_at": now,
            }
        )
        db.add(BKTCountedOpportunityRow(**counted.model_dump()))
    for estimate in report.estimates:
        mastery = MasteryEstimate.model_validate(
            {
                "id": derived_id("bkt-estimate", learner_id, estimate.concept_id, version),
                "learner_id": learner_id,
                "concept_id": estimate.concept_id,
                "algorithm": ALGORITHM,
                "algorithm_version": ALGORITHM_VERSION,
                "parameter_version": version,
                "p_known": estimate.p_known,
                "calibrated": report.parameters.calibrated,
                "source_observation_ids": estimate.source_observation_ids[-MAX_ESTIMATE_SOURCES:],
                "provenance": _estimate_provenance(events, set(estimate.source_observation_ids)),
                "computed_at": now,
            }
        )
        db.add(MasteryEstimateRow(**mastery.model_dump()))
    db.flush()


def replay_learner(
    db: DbSession,
    learner_id: str,
    now: datetime,
    parameter_version: str = DEFAULT_PARAMETERS.parameter_version,
    *,
    persist: bool = True,
) -> tuple[BKTPredictor, ReplayReport]:
    parameters = get_parameters(db, parameter_version, now)
    events = load_events(db, learner_id)
    predictor, report = replay_events(learner_id, events, parameters)
    if persist:
        _persist(db, report, events, now)
    return predictor, report


def persisted_tracing(db: DbSession, learner_id: str, parameter_version: str) -> PersistedTracing:
    counted = db.execute(
        select(BKTCountedOpportunityRow)
        .where(
            BKTCountedOpportunityRow.learner_id == learner_id,
            BKTCountedOpportunityRow.parameter_version == parameter_version,
        )
        .order_by(BKTCountedOpportunityRow.concept_id, BKTCountedOpportunityRow.sequence)
    ).scalars()
    estimates = db.execute(
        select(MasteryEstimateRow)
        .where(
            MasteryEstimateRow.learner_id == learner_id,
            MasteryEstimateRow.algorithm == ALGORITHM,
            MasteryEstimateRow.parameter_version == parameter_version,
        )
        .order_by(MasteryEstimateRow.concept_id)
    ).scalars()
    return PersistedTracing(
        learner_id=learner_id,
        parameter_version=parameter_version,
        counted=[CountedOpportunity.model_validate(row) for row in counted],
        estimates=[MasteryEstimate.model_validate(row) for row in estimates],
    )
