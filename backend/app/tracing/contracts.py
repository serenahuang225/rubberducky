"""Versioned contracts for statistical learner tracing.

These are data contracts. The statistical model itself lives in :mod:`app.tracing.bkt` and
:mod:`app.tracing.predictor`; language models are unrelated to this package.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.common import (
    Confidence,
    ContractModel,
    EntityId,
    Provenance,
    ShortText,
    UtcDatetime,
)
from app.schemas.evidence import MasteryEstimate

ALGORITHM = "bkt"
ALGORITHM_VERSION = "bkt-numpy.v1"
# Bump when the rules deciding which raw events enter the independent stream change.
ELIGIBILITY_VERSION = "bkt-eligibility.v1"

# What the predictor's probability is about. A BKT latent-knowledge value is reported
# separately and is never this quantity.
PredictionTarget = Literal["next_independent_response_correct"]
PREDICTION_TARGET: PredictionTarget = "next_independent_response_correct"

ParameterVersion = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.:-]+$")]
OpportunityKey = Annotated[str, Field(min_length=1, max_length=160)]

IneligibleReason = Literal[
    "no_concept",
    "no_response_correctness",
    "not_verified_assessment",
    "no_assessment_record",
    "explanation_not_response_opportunity",
    "assessment_outcome_mismatch",
    "assisted",
    "independent_reasoning_missing",
    "hint_in_attempt",
    "answer_revealed",
]
UpdateStatus = Literal[
    "counted",
    "ineligible",
    "duplicate_opportunity",
    "already_observed",
    "impossible_observation",
]


class BKTParameters(ContractModel):
    """One immutable, versioned BKT parameter set.

    Every value must be finite and in [0, 1]. Additionally ``p_guess + p_slip < 1``: at or
    above 1 a correct response would not raise (or would lower) belief that the skill is
    known, so the model would be degenerate or inverted. Hand-set values are never
    calibrated.
    """

    schema_version: Literal["bkt-parameters.v1"] = "bkt-parameters.v1"
    parameter_version: ParameterVersion
    p_init: Confidence
    p_learn: Confidence
    p_guess: Confidence
    p_slip: Confidence
    source: Literal["hand_set", "fitted"] = "hand_set"
    calibrated: bool = False
    description: ShortText

    @model_validator(mode="after")
    def _identifiable(self) -> Self:
        if self.p_guess + self.p_slip >= 1.0:
            raise ValueError("p_guess + p_slip must be < 1 for an identifiable BKT model")
        if self.calibrated and self.source != "fitted":
            raise ValueError("only fitted parameters may be marked calibrated")
        return self


DEFAULT_PARAMETERS = BKTParameters(
    parameter_version="bkt-handset.v1",
    p_init=0.2,
    p_learn=0.1,
    p_guess=0.25,
    p_slip=0.1,
    source="hand_set",
    calibrated=False,
    description="Hand-chosen illustrative values; uncalibrated and not fitted to any data.",
)


class TracingEvent(ContractModel):
    """One raw observation viewed through the eligibility rules. It is never modified."""

    schema_version: Literal["tracing-event.v1"] = "tracing-event.v1"
    observation_id: EntityId
    learner_id: EntityId
    concept_id: EntityId | None
    correct: bool | None
    source_type: Annotated[str, Field(max_length=32)]
    source_id: EntityId
    assessment_id: EntityId | None = None
    assessment_kind: Annotated[str, Field(max_length=32)] | None = None
    problem_id: EntityId | None = None
    opportunity_key: OpportunityKey | None = None
    eligible: bool
    ineligible_reason: IneligibleReason | None = None
    provenance: Provenance
    observed_at: UtcDatetime

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.eligible:
            if self.ineligible_reason is not None:
                raise ValueError("eligible events carry no ineligible_reason")
            if self.concept_id is None or self.correct is None or self.opportunity_key is None:
                raise ValueError("eligible events need concept, correctness and opportunity")
        elif self.ineligible_reason is None:
            raise ValueError("ineligible events must say why")
        return self


class ResponsePrediction(ContractModel):
    """A prediction made before the response is observed.

    ``p_correct`` is the probability of the target response. ``latent_knowledge`` is only
    set by predictors with an explicit latent state (BKT); a sequence model such as a GRU
    leaves it ``None`` rather than relabeling its response probability as knowledge.
    """

    schema_version: Literal["response-prediction.v1"] = "response-prediction.v1"
    target: PredictionTarget = PREDICTION_TARGET
    concept_id: EntityId
    p_correct: Confidence
    latent_knowledge: Confidence | None
    algorithm: Annotated[str, Field(max_length=40)]
    algorithm_version: Annotated[str, Field(max_length=40)]
    parameter_version: Annotated[str, Field(max_length=40)]
    calibrated: bool
    opportunities_counted: Annotated[int, Field(ge=0)]


class TracingUpdate(ContractModel):
    """What the predictor did with one raw event, including events that changed nothing."""

    schema_version: Literal["tracing-update.v1"] = "tracing-update.v1"
    observation_id: EntityId
    concept_id: EntityId | None
    opportunity_key: OpportunityKey | None
    status: UpdateStatus
    reason: Annotated[str, Field(max_length=200)] | None = None
    sequence: Annotated[int, Field(ge=1)] | None = None
    prediction: ResponsePrediction | None = None
    observed_correct: bool | None = None
    p_known_posterior: Confidence | None = None
    p_known_after: Confidence | None = None


class ConceptState(ContractModel):
    concept_id: EntityId
    p_known: Confidence
    opportunity_keys: list[OpportunityKey]
    observation_ids: list[EntityId]


class PredictorMetadata(ContractModel):
    schema_version: Literal["predictor-metadata.v1"] = "predictor-metadata.v1"
    algorithm: Annotated[str, Field(max_length=40)]
    algorithm_version: Annotated[str, Field(max_length=40)]
    eligibility_version: Annotated[str, Field(max_length=40)]
    parameter_version: Annotated[str, Field(max_length=40)]
    target: PredictionTarget = PREDICTION_TARGET
    has_latent_state: bool
    calibrated: bool


class BKTSnapshot(ContractModel):
    """Saved BKT predictor state. Loading checks versions so histories are never mixed."""

    schema_version: Literal["bkt-snapshot.v1"] = "bkt-snapshot.v1"
    metadata: PredictorMetadata
    learner_id: EntityId
    parameters: BKTParameters
    concepts: list[ConceptState]
    # Observations already applied (counted or impossible), in order.
    observed_ids: list[EntityId]


class CountedOpportunity(ContractModel):
    """A persisted, derived ledger row for one counted independent opportunity."""

    schema_version: Literal["bkt-counted-opportunity.v1"] = "bkt-counted-opportunity.v1"
    id: EntityId
    learner_id: EntityId
    concept_id: EntityId
    parameter_version: ParameterVersion
    algorithm_version: Annotated[str, Field(max_length=40)]
    eligibility_version: Annotated[str, Field(max_length=40)]
    observation_id: EntityId
    opportunity_key: OpportunityKey
    sequence: Annotated[int, Field(ge=1)]
    p_known_before: Confidence
    p_correct_predicted: Confidence
    observed_correct: bool
    p_known_posterior: Confidence
    p_known_after: Confidence
    computed_at: UtcDatetime


class ConceptEstimate(ContractModel):
    concept_id: EntityId
    p_known: Confidence
    counted_opportunities: Annotated[int, Field(ge=0)]
    source_observation_ids: list[EntityId]


class ReplayReport(ContractModel):
    """Deterministic result of replaying a learner's raw evidence from ``p_init``."""

    schema_version: Literal["bkt-replay-report.v1"] = "bkt-replay-report.v1"
    learner_id: EntityId
    metadata: PredictorMetadata
    parameters: BKTParameters
    raw_event_ids: list[EntityId]
    updates: list[TracingUpdate]
    estimates: list[ConceptEstimate]
    counted_opportunities: Annotated[int, Field(ge=0)]
    note: ShortText = (
        "Latent-knowledge estimates from hand-set, uncalibrated parameters; not a mastery claim."
    )


class PersistedTracing(ContractModel):
    """Derived tracing rows currently stored for one learner and parameter version."""

    schema_version: Literal["bkt-persisted-state.v1"] = "bkt-persisted-state.v1"
    learner_id: EntityId
    parameter_version: ParameterVersion
    counted: list[CountedOpportunity]
    estimates: list[MasteryEstimate]


ReadinessBand = Literal["not_enough_evidence", "emerging", "developing", "strong_so_far"]
TransferStatus = Literal[
    "not_attempted",
    "assisted_or_unverified_only",
    "independent_not_yet_correct",
    "independent_correct",
]


class ConceptReadiness(ContractModel):
    """Learner-facing qualitative projection. It deliberately exposes no probability."""

    schema_version: Literal["concept-readiness.v1"] = "concept-readiness.v1"
    concept_id: EntityId
    readiness: ReadinessBand
    counted_independent_opportunities: Annotated[int, Field(ge=0)]
    independent_transfer: TransferStatus
    calibrated: Literal[False] = False
    parameter_version: ParameterVersion
    note: ShortText


class ReadinessReport(ContractModel):
    schema_version: Literal["readiness-report.v1"] = "readiness-report.v1"
    concepts: list[ConceptReadiness]
