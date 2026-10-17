"""Contracts for tutor turns: requests, the provider draft and the committed turn result.

A provider produces a :class:`TutorDraft`. It separates the public utterance from operational
fields (action, cited evidence, hint level, disclosure, drawing proposals, expected learner
action, memory proposals and a concise decision justification). No hidden chain-of-thought is
requested or stored. The draft only proposes; the coordinator validates it against the
deterministic policy plan, the verifier and the bounded context before anything is committed.
"""

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import Confidence, ContractModel, EntityId, ShortText, UtcDatetime
from app.schemas.learner import (
    Appearance,
    ComfortOverride,
    Personality,
    Session,
    TutorConfiguration,
)
from app.schemas.memory import MemoryUpdateResult
from app.verification.contracts import VerificationResult, VerificationStatus
from app.verification.explanation import ExplanationJudgment

TurnKind = Literal["check_in", "work"]
TurnStatus = Literal["pending", "committed", "rejected", "failed", "superseded"]
ActionType = Literal[
    "check_in_and_pose",
    "confirm_ink",
    "ask_rephrase",
    "step_feedback",
    "diagnostic_hint",
    "step_not_equivalent",
    "reasoning_check",
    "solution_feedback",
    "feedback_and_transfer",
    "transfer_feedback_and_explain",
    "explanation_feedback",
    "explanation_follow_up",
    "smaller_scaffold",
    "change_representation",
    "explain_on_request",
    "wrap_up",
]
Representation = Literal[
    "outside_factor",
    "groups_picture",
    "number_case",
    "copy_check",
    "worked_step",
    "next_step",
]
SupportChange = Literal["none", "reduced"]
HelpMode = Literal["hint", "explain"]
Pace = Literal["standard", "lighter"]
Energy = Literal["ready", "a_bit_tired", "tired"]
GoalChoice = Literal["solve_equations_with_parentheses", "explain_distribution"]
WorkInputMode = Literal["typed", "confirmed_ink", "unconfirmed_ink"]
WorkClassification = Literal[
    "not_sure",
    "explain_request",
    "solution_with_questionable_reasoning",
    "unconfirmed_ink",
    "unsupported",
    "valid_step",
    "partial_distribution",
    "invalid_step",
    "solution_with_reasoning",
    "solution_without_reasoning",
    "wrong_solution",
    "explanation",
]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]

MAX_UTTERANCE_CHARS = 400
MAX_WORK_CHARS = 500


class _Request(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CheckInRequest(_Request):
    """A short self-report check-in. It is never assessed as mathematical evidence."""

    schema_version: Literal["check-in-request.v1"] = "check-in-request.v1"
    expected_revision: Annotated[int, Field(ge=0)]
    goal: GoalChoice = "solve_equations_with_parentheses"
    energy: Energy | None = None


class WorkRequest(_Request):
    """A typed or explicitly confirmed step, an answer or an explanation.

    ``unconfirmed_ink`` is accepted only so the tutor can ask for confirmation; it is never
    stored as a step or assessed.
    """

    schema_version: Literal["work-request.v1"] = "work-request.v1"
    expected_revision: Annotated[int, Field(ge=0)]
    text: Annotated[str, Field(min_length=1, max_length=MAX_WORK_CHARS)]
    input_mode: WorkInputMode = "typed"


class HelpRequest(_Request):
    """An explicit Help me press: a hint (or, on request, an explanation) right now.

    It is a learner self-report, never mathematical evidence, and needs no timer to expire.
    """

    schema_version: Literal["help-request.v1"] = "help-request.v1"
    expected_revision: Annotated[int, Field(ge=0)]
    mode: HelpMode = "hint"


InterruptReason = Literal["student_interrupt", "speech_barge_in"]


class InterruptRequest(_Request):
    """Stop whatever tutor reply is still being prepared for this session.

    ``observed_epoch`` is the cancellation epoch the client last saw (from session state or a
    turn result). The epoch advances at most once per observed value, so a retried request
    whose acknowledgment was lost reports ``replayed`` instead of cancelling twice.
    """

    schema_version: Literal["interrupt-request.v1"] = "interrupt-request.v1"
    observed_epoch: Annotated[int, Field(ge=0)]
    reason: InterruptReason = "student_interrupt"


class InterruptResult(ContractModel):
    schema_version: Literal["interrupt-result.v1"] = "interrupt-result.v1"
    session_id: EntityId
    cancellation_epoch: Annotated[int, Field(ge=0)]
    session_revision: Annotated[int, Field(ge=0)]
    interrupted_turn_ids: list[EntityId] = Field(default_factory=list)
    replayed: bool = False


class TutorDraft(ContractModel):
    """What a provider proposes for one turn. Every field is validated before commit."""

    schema_version: Literal["tutor-draft.v1"] = "tutor-draft.v1"
    turn_id: EntityId
    session_revision: Annotated[int, Field(ge=0)]
    action_type: ActionType
    utterance: Annotated[str, Field(min_length=1, max_length=MAX_UTTERANCE_CHARS)]
    target_concept_ids: Annotated[list[EntityId], Field(min_length=1, max_length=4)]
    evidence_ids: Annotated[list[EntityId], Field(max_length=12)]
    hint_level: Annotated[int, Field(ge=0, le=5)]
    answer_revealed: bool
    drawing_actions: Annotated[list[dict[str, Any]], Field(max_length=24)]
    expected_student_action: Annotated[str, Field(min_length=1, max_length=160)]
    proposed_memory_updates: Annotated[list[dict[str, Any]], Field(max_length=10)]
    # The provider's own reading of the learner's step. It can never override the verifier.
    step_assessment: VerificationStatus | None = None
    decision_justification: Annotated[str, Field(min_length=1, max_length=200)]


class ProviderLabel(ContractModel):
    name: Annotated[str, Field(max_length=40)]
    is_mock: bool
    label: Annotated[str, Field(max_length=120)]


class ProblemView(ContractModel):
    problem_id: EntityId
    attempt_id: EntityId
    statement: ShortText
    kind: Literal["practice", "transfer", "explanation"]
    concept_id: EntityId
    statement_object_id: EntityId | None = None


class HypothesisView(ContractModel):
    """A tentative inference with its confidence, alternatives and actual sources."""

    id: EntityId
    label: ShortText
    confidence: Confidence
    alternatives: list[ShortText]
    status: Annotated[str, Field(max_length=16)]
    evidence_kind: Literal["inference"] = "inference"
    source_ids: list[EntityId]
    # Observations that argue against the hypothesis. They keep it tentative or lower it.
    contradicting_source_ids: list[EntityId] = Field(default_factory=list)
    # True when some counterevidence is substantive (unassisted), not just a weak hinted echo.
    substantive_counterevidence: bool = False


class ReasoningAssessment(ContractModel):
    """A bounded pedagogical reading of the learner's stated reasoning, apart from the verifier.

    The verifier decides whether a value is mathematically right. This records only that
    the stated method looks questionable; it is an inference with a low confidence cap and
    never marks the learner or the value wrong.
    """

    judgment_scope: Literal["pedagogical"] = "pedagogical"
    evidence_kind: Literal["inference"] = "inference"
    status: Literal["questionable"] = "questionable"
    pattern: Annotated[str, Field(max_length=40)]
    confidence: Confidence
    explanation_text: Annotated[str, Field(max_length=MAX_WORK_CHARS)]


class EligibilityNote(ContractModel):
    """Whether one new raw observation entered the independent BKT stream, and why not."""

    observation_id: EntityId
    evidence_kind: Annotated[str, Field(max_length=32)]
    source_type: Annotated[str, Field(max_length=32)]
    assisted: bool
    eligible: bool
    reason: Annotated[str, Field(max_length=64)] | None = None
    update_status: Annotated[str, Field(max_length=32)] | None = None


class StudentInputOutcome(ContractModel):
    input_mode: WorkInputMode | Literal["check_in", "help_button"]
    text: Annotated[str, Field(max_length=MAX_WORK_CHARS)] | None = None
    classification: WorkClassification | Literal["check_in"]
    step_id: EntityId | None = None
    observation_ids: list[EntityId] = Field(default_factory=list)
    assessment_id: EntityId | None = None
    assessment_kind: Annotated[str, Field(max_length=32)] | None = None
    assessment_independent: bool | None = None
    verification: VerificationResult | None = None
    reasoning_assessment: ReasoningAssessment | None = None
    explanation_judgment: ExplanationJudgment | None = None
    eligibility: list[EligibilityNote] = Field(default_factory=list)


class TurnRejection(ContractModel):
    code: Annotated[str, Field(max_length=40)]
    message: Annotated[str, Field(max_length=200)]


class CommittedDrawing(ContractModel):
    object_id: EntityId
    tool: Annotated[str, Field(max_length=40)]
    semantic_role: Annotated[str, Field(max_length=40)]


class TutorTurnResult(ContractModel):
    """The authoritative outcome of one turn, as stored and as returned to the client.

    Only ``status='committed'`` results carry tutor text, hints, drawings or memory
    effects. Student evidence recorded when the turn was reserved is reported in
    ``student_input`` whatever the provider later did.
    """

    schema_version: Literal["tutor-turn-result.v1"] = "tutor-turn-result.v1"
    turn_id: EntityId
    session_id: EntityId
    kind: TurnKind
    status: TurnStatus
    base_revision: Annotated[int, Field(ge=0)]
    session_revision: Annotated[int, Field(ge=0)]
    # The cancellation epoch this turn was reserved under; output is valid only under it.
    cancellation_epoch: Annotated[int, Field(ge=0)] = 0
    provider: ProviderLabel
    student_input: StudentInputOutcome | None = None
    current_problem: ProblemView | None = None
    pace: Pace = "standard"
    action_type: ActionType
    utterance: Annotated[str, Field(max_length=MAX_UTTERANCE_CHARS)] | None = None
    expected_student_action: Annotated[str, Field(max_length=160)] | None = None
    target_concept_ids: list[EntityId] = Field(default_factory=list)
    evidence_ids: list[EntityId] = Field(default_factory=list)
    hypothesis: HypothesisView | None = None
    hint_id: EntityId | None = None
    hint_level: Annotated[int, Field(ge=0, le=5)] = 0
    answer_revealed: bool = False
    representation: Representation | None = None
    support_change: SupportChange = "none"
    drawings: list[CommittedDrawing] = Field(default_factory=list)
    memory: MemoryUpdateResult | None = None
    decision_justification: Annotated[str, Field(max_length=200)] | None = None
    context_source_ids: list[EntityId] = Field(default_factory=list)
    rejections: list[TurnRejection] = Field(default_factory=list)
    replayed: bool = False
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None


class PersonaOptions(ContractModel):
    appearances: list[Appearance]
    personalities: list[Personality]
    comfort_overrides: list[ComfortOverride]
    note: ShortText = "Appearance and personality are chosen separately; none implies ability."


class TutorConfigurationRequest(_Request):
    """Persona choice. Appearance and personality are independent axes; neither implies ability.

    The comfort override takes effect immediately and never touches the other axes; leaving it
    out keeps the current override (``none`` on the first selection).
    """

    schema_version: Literal["tutor-configuration-request.v1"] = "tutor-configuration-request.v1"
    appearance: Appearance
    personality: Personality
    comfort_override: ComfortOverride | None = None


class SessionState(ContractModel):
    """Everything a client needs to resume a session: problem, revision, pace and persona."""

    schema_version: Literal["session-state.v1"] = "session-state.v1"
    session: Session
    current_problem: ProblemView | None = None
    pace: Pace = "standard"
    pending_turn_id: EntityId | None = None
    # Temporary session context from another sitting exists and must be rechecked, not reused.
    session_context_recheck: bool = False
    persona: TutorConfiguration | None = None
