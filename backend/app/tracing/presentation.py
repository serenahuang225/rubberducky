"""Learner-facing qualitative projection of uncalibrated BKT estimates.

The bands are coarse on purpose: hand-set parameters do not justify showing a probability
or a mastery claim to a learner. Independent transfer status is reported separately because
a strong practice estimate is not evidence of transfer.
"""

from app.tracing.contracts import (
    ConceptReadiness,
    ReadinessBand,
    ReadinessReport,
    TracingEvent,
    TransferStatus,
)
from app.tracing.predictor import BKTPredictor

EMERGING_BELOW = 0.4
DEVELOPING_BELOW = 0.75


def readiness_band(p_known: float, counted_opportunities: int) -> ReadinessBand:
    if counted_opportunities == 0:
        return "not_enough_evidence"
    if p_known < EMERGING_BELOW:
        return "emerging"
    if p_known < DEVELOPING_BELOW:
        return "developing"
    return "strong_so_far"


def transfer_status(events: list[TracingEvent], concept_id: str) -> TransferStatus:
    transfers = [
        event
        for event in events
        if event.concept_id == concept_id and event.assessment_kind == "transfer_check"
    ]
    independent = [event for event in transfers if event.eligible]
    if any(event.correct for event in independent):
        return "independent_correct"
    if independent:
        return "independent_not_yet_correct"
    if transfers:
        return "assisted_or_unverified_only"
    return "not_attempted"


def readiness_report(events: list[TracingEvent], predictor: BKTPredictor) -> ReadinessReport:
    concept_ids = sorted(
        {event.concept_id for event in events if event.concept_id is not None}
        | set(predictor.concepts())
    )
    calibration = "calibrated" if predictor.parameters.calibrated else "uncalibrated hand-set"
    concepts = []
    for concept_id in concept_ids:
        counted = len(predictor.counted_opportunities(concept_id))
        concepts.append(
            ConceptReadiness(
                concept_id=concept_id,
                readiness=readiness_band(predictor.p_known(concept_id), counted),
                counted_independent_opportunities=counted,
                independent_transfer=transfer_status(events, concept_id),
                parameter_version=predictor.parameters.parameter_version,
                note=f"Qualitative band from {calibration} parameters; not a mastery score.",
            )
        )
    return ReadinessReport(concepts=concepts)
