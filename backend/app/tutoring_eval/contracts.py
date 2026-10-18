"""Typed contracts for replay cases, candidate responses and scored rows.

A case is a fictional learner timeline plus the turns to replay. A *snapshot* is what a
candidate is allowed to see for one turn: only history strictly before the turn, bounded,
with source IDs. Scores are per dimension and may be missing (``None``) when a dimension
does not apply or could not be measured; a missing score is never filled in.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId, UtcDatetime

HistoryKind = Literal[
    "tutor_hint", "learner_work", "learner_message", "self_report", "preference", "assessment"
]

DIMENSIONS: tuple[str, ...] = (
    "math",
    "diagnosis",
    "disclosure",
    "hint_specificity",
    "hint_usefulness",
    "respect",
    "memory_grounding",
)
Dimension = Literal[
    "math",
    "diagnosis",
    "disclosure",
    "hint_specificity",
    "hint_usefulness",
    "respect",
    "memory_grounding",
]

DEFAULT_MAX_HISTORY = 6
MAX_HISTORY_LIMIT = 20


class HistoryEvent(ContractModel):
    source_id: EntityId
    occurred_at: UtcDatetime
    kind: HistoryKind
    text: Annotated[str, Field(min_length=1, max_length=300)]


class TurnExpectation(ContractModel):
    """What a good tutor reply does for this turn. All matching is deterministic text matching."""

    # Mathematical claims the reply must not make (compared with whitespace removed).
    wrong_claims: list[str] = Field(default_factory=list, max_length=12)
    # Mathematical statements known to be true here; stating one counts as a correct claim.
    correct_claims: list[str] = Field(default_factory=list, max_length=12)
    # Completed steps or answers the reply must not show unless an explanation was requested.
    answer_strings: list[str] = Field(default_factory=list, max_length=12)
    allow_explanation: bool = False
    # Each group is satisfied by any one of its cues; a diagnostic reply covers every group.
    diagnostic_cues: list[list[str]] = Field(default_factory=list, max_length=6)
    # Case-specific tokens a specific hint refers to (the problem's own terms).
    anchors: list[str] = Field(default_factory=list, max_length=12)
    expects_hint: bool = False
    max_words: Annotated[int, Field(ge=5, le=200)] = 60
    # A reply should acknowledge the learner's stated state (for example tiredness).
    acknowledge_state: bool = False
    # History sources a grounded reply should cite.
    expected_memory_source_ids: list[EntityId] = Field(default_factory=list, max_length=8)


class ReplayTurn(ContractModel):
    turn_id: EntityId
    occurred_at: UtcDatetime
    learner_message: Annotated[str, Field(min_length=1, max_length=300)]
    problem_statement: Annotated[str, Field(min_length=1, max_length=200)]
    expectation: TurnExpectation


class ReplayCase(ContractModel):
    schema_version: Literal["tutoring-replay-case.v1"] = "tutoring-replay-case.v1"
    case_id: EntityId
    title: Annotated[str, Field(min_length=1, max_length=120)]
    scenario: Annotated[str, Field(min_length=1, max_length=80)]
    # Cases are authored fictional timelines, never real learner data.
    is_fictional: Literal[True] = True
    # Includes events after some turns on purpose; replay must exclude them per turn.
    history: list[HistoryEvent] = Field(max_length=60)
    turns: Annotated[list[ReplayTurn], Field(min_length=1, max_length=8)]


class ReplaySnapshot(ContractModel):
    schema_version: Literal["tutoring-replay-snapshot.v1"] = "tutoring-replay-snapshot.v1"
    case_id: EntityId
    turn_id: EntityId
    scenario: str
    cutoff: UtcDatetime
    learner_message: str
    problem_statement: str
    history: list[HistoryEvent]
    # Equals the IDs in ``history``: the only IDs a reply may cite.
    available_source_ids: list[EntityId]
    omitted_future_events: Annotated[int, Field(ge=0)]
    omitted_by_bound: Annotated[int, Field(ge=0)]
    expectation: TurnExpectation
    digest: str


class CandidateResponse(ContractModel):
    text: Annotated[str, Field(min_length=1, max_length=1200)]
    cited_source_ids: list[EntityId] = Field(default_factory=list, max_length=12)
    # The candidate's own claim about whether it revealed the answer; None when not stated.
    answer_revealed: bool | None = None


class DimensionScore(ContractModel):
    dimension: Dimension
    # None means "does not apply" or "could not be measured", never a zero.
    value: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None
    detail: Annotated[str, Field(max_length=200)]


LatencySource = Literal["measured_local_call", "supplied_by_candidate_source", "missing"]


class RowResult(ContractModel):
    case_id: EntityId
    turn_id: EntityId
    scenario: str
    snapshot_digest: str
    response: CandidateResponse | None
    # Sanitized exception type and message when the candidate failed for this row.
    error: str | None
    scores: list[DimensionScore]
    latency_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None
    latency_source: LatencySource
    # 1.0 when the reply is within the latency budget, falling to 0.0 at twice the budget.
    latency_score: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None


class DimensionSummary(ContractModel):
    dimension: str
    mean: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None
    scored_rows: Annotated[int, Field(ge=0)]
    missing_rows: Annotated[int, Field(ge=0)]


class RunClaims(ContractModel):
    """What this report does and does not establish; the defaults are the honest ones."""

    trained_model_result: Literal[False] = False
    learning_gain_claim: Literal[False] = False
    judge_scores_included: bool = False
    note: str = (
        "Deterministic rubric scores over a small authored fixture set. Not a trained-model "
        "comparison and not evidence of learning gain."
    )


class EvaluationReport(ContractModel):
    schema_version: Literal["tutoring-evaluation-report.v1"] = "tutoring-evaluation-report.v1"
    kind: Literal["deterministic"] = "deterministic"
    rubric_version: str
    candidate_name: str
    candidate_label: Literal["fixture", "external_responses", "callable"]
    latency_budget_ms: float
    rows: list[RowResult]
    dimensions: list[DimensionSummary]
    latency_mean_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None
    latency_rows_missing: Annotated[int, Field(ge=0)]
    errors: Annotated[int, Field(ge=0)]
    claims: RunClaims = Field(default_factory=RunClaims)


class JudgeRating(ContractModel):
    rating: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    rationale: Annotated[str, Field(max_length=300)]


class JudgedRow(ContractModel):
    case_id: EntityId
    turn_id: EntityId
    rating: JudgeRating | None
    error: str | None


class JudgedSummary(ContractModel):
    """Model-judged ratings, kept apart from the deterministic scores and never averaged in."""

    schema_version: Literal["tutoring-judged-ratings.v1"] = "tutoring-judged-ratings.v1"
    kind: Literal["model_judged"] = "model_judged"
    judge_name: str
    rows: list[JudgedRow]
    mean_rating: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None
    errors: Annotated[int, Field(ge=0)]
