"""Raw learning evidence and derived-belief contracts.

Raw evidence (attempts, steps, observations, hints, assessments) is stored separately from
derived beliefs (hypotheses, mastery estimates) so corrections can trigger recomputation.
Unmeasured values such as correctness or latency stay ``None``; they are never filled in.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.common import (
    Confidence,
    ContractModel,
    EntityId,
    EvidenceKind,
    LongText,
    Provenance,
    ShortText,
    SourceIds,
    UtcDatetime,
)

StepInputMode = Literal["typed", "confirmed_ink"]
ObservationSource = Literal[
    "step", "attempt", "assessment", "check_in", "hint", "hypothesis", "explanation"
]
AssessmentKind = Literal["practice_check", "transfer_check", "explanation_check"]
AssessmentOutcome = Literal["correct", "incorrect", "unknown"]
HypothesisStatus = Literal["tentative", "supported", "contradicted", "retracted"]

_CORRECTNESS_KINDS: frozenset[str] = frozenset({"observed_work", "verified_assessment"})


class Attempt(ContractModel):
    schema_version: Literal["attempt.v1"] = "attempt.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId
    problem_id: EntityId
    provenance: Provenance
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None


class Step(ContractModel):
    """A typed or explicitly confirmed step. Unconfirmed raw ink is never a Step."""

    schema_version: Literal["step.v1"] = "step.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId
    attempt_id: EntityId
    sequence: Annotated[int, Field(ge=0, le=1000)]
    input_mode: StepInputMode
    content: LongText
    provenance: Provenance
    submitted_at: UtcDatetime


class Observation(ContractModel):
    schema_version: Literal["observation.v1"] = "observation.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId | None = None
    source_type: ObservationSource
    source_id: EntityId
    evidence_kind: EvidenceKind
    concept_id: EntityId | None = None
    correct: bool | None = None
    latency_ms: Annotated[int, Field(ge=0, le=86_400_000)] | None = None
    confidence: Confidence
    assisted: bool = False
    provenance: Provenance
    observed_at: UtcDatetime
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _correctness_needs_work(self) -> Self:
        if self.correct is not None and self.evidence_kind not in _CORRECTNESS_KINDS:
            raise ValueError("only observed work or verified assessments carry correctness")
        return self


class Hint(ContractModel):
    schema_version: Literal["hint.v1"] = "hint.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId
    attempt_id: EntityId | None = None
    concept_id: EntityId | None = None
    level: Annotated[int, Field(ge=0, le=5)]
    answer_revealed: bool
    content: LongText
    provenance: Provenance
    given_at: UtcDatetime


class Assessment(ContractModel):
    """Assessment of a problem attempt; ``kind='transfer_check'`` is a TransferCheck."""

    schema_version: Literal["assessment.v1"] = "assessment.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId
    attempt_id: EntityId
    problem_id: EntityId
    kind: AssessmentKind
    independent: bool
    outcome: AssessmentOutcome
    provenance: Provenance
    assessed_at: UtcDatetime


class TransferCheck(Assessment):
    kind: Literal["transfer_check"] = "transfer_check"


class MisconceptionHypothesis(ContractModel):
    """A tentative inference. It always keeps its confidence, alternatives and sources."""

    schema_version: Literal["misconception-hypothesis.v1"] = "misconception-hypothesis.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId | None = None
    concept_id: EntityId
    label: ShortText
    description: LongText
    confidence: Confidence
    alternatives: Annotated[list[ShortText], Field(max_length=5)]
    status: HypothesisStatus = "tentative"
    evidence_kind: Literal["inference"] = "inference"
    source_ids: Annotated[SourceIds, Field(min_length=1)]
    provenance: Provenance
    created_at: UtcDatetime
    updated_at: UtcDatetime


class MasteryEstimate(ContractModel):
    """Derived latent-knowledge estimate; not a calibrated claim of mastery."""

    schema_version: Literal["mastery-estimate.v1"] = "mastery-estimate.v1"
    id: EntityId
    learner_id: EntityId
    concept_id: EntityId
    algorithm: Annotated[str, Field(min_length=1, max_length=40)]
    algorithm_version: Annotated[str, Field(min_length=1, max_length=40)]
    parameter_version: Annotated[str, Field(min_length=1, max_length=40)]
    p_known: Confidence
    calibrated: bool = False
    source_observation_ids: SourceIds
    provenance: Provenance
    computed_at: UtcDatetime
