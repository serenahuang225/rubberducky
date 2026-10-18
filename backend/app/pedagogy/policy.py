"""Deterministic tutoring policy over typed evidence.

The policy decides the teaching move; a provider only words it. Order of concerns: goal and
current work, then verification (never overridden), then the smallest useful intervention,
then feedback, fading and a fresh independent transfer. Every plan lists the evidence it is
grounded in, what must not be disclosed yet, and the action expected from the learner.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import Field

from app.pedagogy.intents import (
    REASONING_CONFIDENCE,
    HelpIntent,
    help_intent,
    questionable_reasoning,
    split_claim_and_reasoning,
)
from app.pedagogy.problems import (
    GROUP_MARK_OFFSET,
    STATEMENT_Y,
    ProblemSpec,
)
from app.pedagogy.scaffolds import (
    choose_move,
    representation_drawings,
)
from app.schemas.common import ContractModel, EntityId
from app.schemas.learner import ComfortOverride, Personality
from app.schemas.tutor import (
    ActionType,
    Energy,
    HypothesisView,
    Pace,
    ProblemView,
    ReasoningAssessment,
    Representation,
    SupportChange,
    WorkClassification,
    WorkInputMode,
)
from app.verification import WorkSource, check_solution, check_step
from app.verification.contracts import VerificationResult
from app.verification.explanation import ExplanationJudgment

PLAN_VERSION: Literal["tutor-policy.v1"] = "tutor-policy.v1"
PARTIAL_DISTRIBUTION_LABEL = "Partial distribution"
PARTIAL_DISTRIBUTION_ALTERNATIVES = ("Copying slip", "Unsure how parentheses group terms")
# Tentative by construction: one matching step is weak evidence about a person.
PARTIAL_DISTRIBUTION_CONFIDENCE = 0.5
EXPLANATION_ADEQUATE_CRITERIA = 2

MemoryHint = Literal["none", "session_tiredness", "assisted_success_note"]
Tone = Literal["neutral", "correction", "success", "support"]


def normalize(text: str) -> str:
    return "".join(text.lower().split())


@dataclass(frozen=True)
class WorkAnalysis:
    classification: WorkClassification
    verification: VerificationResult | None
    normalized: str | None = None
    is_expanded_step: bool = False
    unresolved_step: str | None = None
    reasoning: ReasoningAssessment | None = None
    # What the learner said about their method, when the value came with an explanation.
    explanation_seen: str | None = None


def _is_solution_claim(result: VerificationResult) -> bool:
    return result.reason in ("solution_matches", "solution_differs")


def _help_analysis(text: str) -> WorkAnalysis | None:
    intent = help_intent(text)
    if intent is None:
        return None
    return WorkAnalysis("explain_request" if intent == "explain_request" else "not_sure", None)


def classify_help(intent: HelpIntent) -> WorkAnalysis:
    """The analysis for an explicit Help me press (no typed words to read)."""
    return WorkAnalysis("explain_request" if intent == "explain_request" else "not_sure", None)


def classify_work(
    spec: ProblemSpec, prior_steps: Sequence[str], text: str, input_mode: WorkInputMode
) -> WorkAnalysis:
    """Classify one submission on ``spec`` using only the bounded verifier.

    A leading mathematical claim is verified on its own; any words after it only inform
    the pedagogical reasoning reading and never the verifier's outcome.
    """
    if spec.kind == "explanation":
        return _help_analysis(text) or WorkAnalysis("explanation", None)
    source = WorkSource(author_role="student", input_mode=input_mode)
    if input_mode == "unconfirmed_ink":
        return WorkAnalysis("unconfirmed_ink", check_step(spec.statement, text, source))
    claim, reasoning_words = split_claim_and_reasoning(text)
    solution = check_solution(spec.statement, claim, source)
    if solution.status == "valid":
        intermediates = []
        for prior in prior_steps:
            prior_claim = split_claim_and_reasoning(prior)[0]
            if _is_solution_claim(check_solution(spec.statement, prior_claim)):
                continue
            intermediates.append((prior_claim, check_step(spec.statement, prior_claim).status))
        if intermediates and intermediates[-1][1] == "valid":
            return WorkAnalysis("solution_with_reasoning", solution, solution.candidate.normalized)
        unresolved = intermediates[-1][0] if intermediates else None
        pattern = questionable_reasoning(spec, reasoning_words)
        if pattern is not None and reasoning_words is not None:
            return WorkAnalysis(
                "solution_with_questionable_reasoning",
                solution,
                solution.candidate.normalized,
                unresolved_step=unresolved,
                reasoning=ReasoningAssessment(
                    pattern=pattern,
                    confidence=REASONING_CONFIDENCE,
                    explanation_text=reasoning_words,
                ),
                explanation_seen=reasoning_words,
            )
        return WorkAnalysis(
            "solution_without_reasoning",
            solution,
            solution.candidate.normalized,
            unresolved_step=unresolved,
            explanation_seen=reasoning_words,
        )
    if solution.status == "invalid" and solution.reason == "solution_differs":
        return WorkAnalysis("wrong_solution", solution, solution.candidate.normalized)
    step = check_step(spec.statement, claim, source)
    if step.status == "valid":
        expanded = spec.expanded_step is not None and normalize(claim) == normalize(
            spec.expanded_step
        )
        return WorkAnalysis(
            "valid_step", step, step.candidate.normalized, is_expanded_step=expanded
        )
    if step.status == "invalid":
        partial = normalize(claim) in {normalize(s) for s in spec.partial_distribution_steps}
        kind: WorkClassification = "partial_distribution" if partial else "invalid_step"
        return WorkAnalysis(kind, step, step.candidate.normalized)
    return _help_analysis(text) or WorkAnalysis("unsupported", step)


class TurnPlan(ContractModel):
    """The policy's decision for one turn. Stored with the turn; never shown as reasoning."""

    schema_version: Literal["turn-plan.v1"] = "turn-plan.v1"
    policy_version: Literal["tutor-policy.v1"] = PLAN_VERSION
    turn_id: EntityId
    action_type: ActionType
    tone: Tone
    message_params: dict[str, str]
    target_concept_ids: Annotated[list[EntityId], Field(min_length=1, max_length=4)]
    context_concept_id: EntityId
    hint_level: Annotated[int, Field(ge=0, le=5)]
    reveal_allowed: bool = False
    forbidden_disclosures: list[str]
    required_evidence_ids: list[EntityId]
    local_source_ids: list[EntityId]
    expected_student_action: Annotated[str, Field(max_length=160)]
    drawing_actions: list[dict[str, Any]]
    memory_hint: MemoryHint = "none"
    pace: Pace = "standard"
    hypothesis: HypothesisView | None = None
    step_status: Literal["valid", "invalid", "unknown"] | None = None
    personality: Personality
    comfort_override: ComfortOverride
    current_problem: ProblemView | None = None
    representation: Representation | None = None
    # A following move that deliberately offers less help than the learner just needed.
    support_change: SupportChange = "none"
    # The attempt the learner was working in when the turn was reserved (None for check-ins).
    worked_attempt_id: EntityId | None = None
    decision_justification: Annotated[str, Field(max_length=200)]


@dataclass(frozen=True)
class Persona:
    personality: Personality = "janelle"
    comfort_override: ComfortOverride = "none"


def _forbidden(spec: ProblemSpec, *, solution_known: bool, expanded_known: bool) -> list[str]:
    """Normalized strings the tutor must not show before the learner has produced them."""
    forbidden: list[str] = []
    if not solution_known:
        forbidden.extend(normalize(claim) for claim in spec.solution_claims())
    if not expanded_known and spec.expanded_step is not None:
        forbidden.append(normalize(spec.expanded_step))
    if not expanded_known and spec.expanded_side is not None:
        forbidden.append(normalize(spec.expanded_side))
    return sorted(set(forbidden))


def _first_step_action(problem: ProblemView) -> str:
    if problem.kind == "explanation":
        return "Type a sentence or two explaining the idea in your own words."
    return f"Type your first step for {problem.statement}."


def plan_check_in(
    *,
    turn_id: str,
    spec: ProblemSpec,
    problem: ProblemView,
    energy: Energy | None,
    check_in_observation_id: str | None,
    reminder_ids: Sequence[str],
    persona: Persona,
) -> TurnPlan:
    lighter = energy in ("tired", "a_bit_tired")
    local = [i for i in (check_in_observation_id,) if i is not None]
    returning = bool(reminder_ids)
    return TurnPlan(
        turn_id=turn_id,
        action_type="check_in_and_pose",
        tone="neutral",
        message_params={
            "statement": problem.statement,
            "kind": problem.kind,
            "energy": energy or "unknown",
            "returning": "yes" if returning else "no",
        },
        target_concept_ids=[spec.concept_id],
        context_concept_id=spec.step_concept_id,
        hint_level=0,
        forbidden_disclosures=_forbidden(spec, solution_known=False, expanded_known=False),
        required_evidence_ids=[*local, *reminder_ids],
        local_source_ids=local,
        expected_student_action=_first_step_action(problem),
        drawing_actions=[],
        memory_hint="session_tiredness" if energy == "tired" else "none",
        pace="lighter" if lighter else "standard",
        personality=persona.personality,
        comfort_override=persona.comfort_override,
        current_problem=problem,
        decision_justification=(
            "Returning: earlier grouping help was assisted, so pose the same problem with a "
            "reminder drawn from that note and leave the work to the learner."
            if returning
            else "New session: pose the unit's first problem and leave the work to the learner."
        ),
    )


def grouping_mark(spec: ProblemSpec, statement_object_id: str) -> list[dict[str, Any]]:
    """Deterministic highlight plus bracket under the parenthesized group."""
    span = spec.group_span()
    if span is None or spec.group_text is None:
        return []
    start, end = span
    y = STATEMENT_Y + GROUP_MARK_OFFSET
    return [
        {
            "tool": "highlight",
            "semantic_role": "emphasis",
            "target_object_id": statement_object_id,
            "term": spec.group_text,
        },
        {
            "tool": "draw_shape",
            "semantic_role": "grouping_mark",
            "shape": "bracket",
            "start": {"x": start, "y": y},
            "end": {"x": end, "y": y},
        },
    ]


@dataclass(frozen=True)
class WorkFacts:
    """Everything the policy needs about one recorded submission."""

    turn_id: str
    spec: ProblemSpec
    problem: ProblemView
    analysis: WorkAnalysis
    text: str
    step_id: str | None
    observation_ids: tuple[str, ...]
    attempt_hint_ids: tuple[str, ...]
    attempt_hint_levels: tuple[int, ...]
    expanded_seen: bool
    hypothesis: HypothesisView | None = None
    assessment_observation_id: str | None = None
    next_problem: ProblemView | None = None
    next_spec: ProblemSpec | None = None
    explanation: ExplanationJudgment | None = None
    explanation_missing: str | None = None
    # An earlier hint in this attempt already showed the completed step.
    attempt_answer_revealed: bool = False


_MISSING_QUESTIONS = {
    "multiplies_each_term": "What does the 2 do to each term inside the parentheses?",
    "groups_as_repeated_addition": "How is 2(x + 3) like two groups of (x + 3)?",
    "preserves_value": "Does rewriting it change the value? How do you know?",
}


def missing_question(criterion_id: str | None) -> str:
    return _MISSING_QUESTIONS.get(criterion_id or "", "Can you say why, not only what?")


def plan_work(facts: WorkFacts, persona: Persona) -> TurnPlan:
    spec, problem, analysis = facts.spec, facts.problem, facts.analysis
    local = [i for i in (facts.step_id, *facts.observation_ids) if i is not None]
    grounded = list(local)
    solution_known = analysis.classification in (
        "solution_with_reasoning",
        "solution_without_reasoning",
        "solution_with_questionable_reasoning",
    )
    helping = analysis.classification in ("not_sure", "explain_request")
    move = None
    if helping or analysis.classification == "partial_distribution":
        move = choose_move(
            spec,
            source=(
                "partial_distribution"
                if analysis.classification == "partial_distribution"
                else (
                    "explain_request"
                    if analysis.classification == "explain_request"
                    else "not_sure"
                )
            ),
            levels=facts.attempt_hint_levels,
            counter_evidence=facts.hypothesis is not None
            and facts.hypothesis.substantive_counterevidence,
        )
    forbidden = _forbidden(
        spec,
        solution_known=solution_known,
        expanded_known=(
            facts.expanded_seen
            or analysis.is_expanded_step
            or facts.attempt_answer_revealed
            or (move is not None and move.reveals)
        ),
    )
    if facts.next_spec is not None:
        # The fresh problem is posed unsolved: its answer and completed step stay hidden too.
        forbidden = sorted(
            {*forbidden, *_forbidden(facts.next_spec, solution_known=False, expanded_known=False)}
        )
    status = None if analysis.verification is None else analysis.verification.status
    params: dict[str, str] = {"statement": problem.statement}
    hint_level = 0
    tone: Tone = "neutral"
    drawings: list[dict[str, Any]] = []
    memory_hint: MemoryHint = "none"
    hypothesis = None
    current = problem
    expected = "Type your next step."
    action: ActionType
    concepts = [spec.concept_id]
    assisted = bool(facts.attempt_hint_ids)
    representation: Representation | None = None
    support_change: SupportChange = "none"
    reveal_allowed = False

    match analysis.classification:
        case "unconfirmed_ink":
            action = "confirm_ink"
            expected = "Type the step, or confirm what your handwriting says."
            justification = "Raw ink is not recognized with certainty, so ask before assessing."
        case "unsupported":
            action = "ask_rephrase"
            expected = "Rewrite the step using numbers, a variable, + - * / and =."
            justification = "The verifier could not check this form; it is unknown, not wrong."
        case "valid_step":
            action = "step_feedback"
            tone = "success"
            params |= {"step": analysis.normalized or facts.text, "factor": spec.factor_text or ""}
            params["expanded"] = "yes" if analysis.is_expanded_step else "no"
            concepts = [spec.step_concept_id]
            if (
                facts.hypothesis is not None
                and analysis.is_expanded_step
                and facts.hypothesis.contradicting_source_ids
            ):
                # A verified full distribution is counterevidence the learner can inspect.
                hypothesis = facts.hypothesis
                grounded.append(hypothesis.id)
                grounded.extend(hypothesis.contradicting_source_ids[-2:])
                justification = (
                    "Verified full distribution argues against the earlier tentative "
                    "hypothesis; acknowledge it and leave the next step."
                )
            else:
                justification = "Verified equivalent step; acknowledge it and leave the next step."
        case "partial_distribution" | "not_sure" | "explain_request":
            assert move is not None  # noqa: S101 - chosen above for exactly these cases
            action = move.action
            tone = "correction" if analysis.classification == "partial_distribution" else "support"
            hint_level = move.level
            representation = move.representation
            reveal_allowed = move.reveals
            params |= move.params | {"level": str(move.level)}
            params["representation"] = move.representation
            concepts = move.concepts
            hypothesis = facts.hypothesis
            if problem.statement_object_id is not None:
                drawings = representation_drawings(
                    spec, move.representation, problem.statement_object_id
                )
            if hypothesis is not None and analysis.classification == "partial_distribution":
                grounded.append(hypothesis.id)
                grounded.extend(hypothesis.contradicting_source_ids[-2:])
            grounded.extend(facts.attempt_hint_ids[-3:])
            expected = move.expected
            justification = move.justification
        case "invalid_step":
            action = "step_not_equivalent"
            tone = "correction"
            hint_level = 1
            expected = "Check which operation you applied and try the step again."
            justification = "Verified not equivalent; ask which operation changed the equation."
        case "solution_without_reasoning":
            action = "reasoning_check"
            params |= {"value": analysis.normalized or facts.text}
            if analysis.unresolved_step is not None:
                params["unresolved"] = analysis.unresolved_step
            if analysis.explanation_seen is not None:
                params["explained"] = "yes"
            expected = "Type one step that shows how you got this value."
            justification = (
                "Correct value, but no checked reasoning yet, so it is not independent evidence."
            )
        case "solution_with_questionable_reasoning":
            action = "reasoning_check"
            hint_level = 1
            params |= {
                "value": analysis.normalized or facts.text,
                "questionable": analysis.reasoning.pattern if analysis.reasoning else "",
                "factor": spec.factor_text or "",
                "group": spec.group_text or "",
            }
            representation = "outside_factor"
            expected = (
                "Say what the outside factor does to each term, or type a step that shows it."
            )
            justification = (
                "Verified value, but the stated method skips a term (a bounded keyword reading); "
                "ask about the method before counting it as independent."
            )
            if problem.statement_object_id is not None:
                drawings = representation_drawings(
                    spec, "outside_factor", problem.statement_object_id
                )
        case "wrong_solution":
            action = "solution_feedback"
            tone = "correction"
            hint_level = 1
            params |= {"claim": analysis.normalized or facts.text}
            expected = "Substitute your value back into the equation and compare both sides."
            justification = "Verified wrong value; suggest substitution as a self-check."
        case "solution_with_reasoning":
            tone = "success"
            params |= {
                "value": analysis.normalized or facts.text,
                "assisted": "yes" if assisted else "no",
                "revealed": "yes" if facts.attempt_answer_revealed else "no",
            }
            grounded.extend(facts.attempt_hint_ids[-4:])
            if facts.assessment_observation_id is not None:
                grounded.append(facts.assessment_observation_id)
            memory_hint = "assisted_success_note" if assisted else "none"
            next_problem = facts.next_problem
            if next_problem is None:
                action = "wrap_up"
                expected = "You can finish here, or start a new session later."
                justification = "Solved with checked steps; no fresh problem remains today."
            else:
                current = next_problem
                params["next_statement"] = next_problem.statement
                if next_problem.kind == "explanation":
                    action = "transfer_feedback_and_explain"
                    expected = "Type a sentence or two explaining the idea in your own words."
                    justification = (
                        "Transfer solved with checked steps; ask for a short explanation next."
                    )
                else:
                    action = "feedback_and_transfer"
                    expected = f"Type your first step for {next_problem.statement}."
                    if assisted:
                        # Support fades: the next problem restarts at the lowest rung and
                        # the tutor holds hints back until the learner asks or needs them.
                        support_change = "reduced"
                        params["support"] = "reduced"
                        justification = (
                            "Solved after help, so offer a fresh variant and hold hints back "
                            "until needed (lower support than this attempt needed)."
                        )
                    else:
                        justification = (
                            "Solved independently; offer a fresh variant with changed numbers."
                        )
            if facts.next_problem is not None:
                concepts = [spec.concept_id]
        case "explanation":
            judgment = facts.explanation
            met = (
                []
                if judgment is None
                else [j.criterion_id for j in judgment.judgments if j.status == "met"]
            )
            concepts = [spec.concept_id]
            if len(met) >= EXPLANATION_ADEQUATE_CRITERIA:
                action = "explanation_feedback"
                tone = "success"
                params |= {"met": ",".join(met)}
                expected = "Choose another problem or finish for today."
                justification = "Explanation names the key ideas (rubric inference, tentative)."
            else:
                action = "explanation_follow_up"
                params |= {
                    "met": ",".join(met),
                    "question": missing_question(facts.explanation_missing),
                }
                expected = "Add a sentence answering the follow-up question."
                justification = "Explanation is incomplete by the rubric; ask a targeted question."
        case _:
            raise ValueError(f"unhandled classification {analysis.classification}")

    return TurnPlan(
        turn_id=facts.turn_id,
        action_type=action,
        tone=tone,
        message_params=params,
        target_concept_ids=concepts,
        context_concept_id=spec.step_concept_id,
        hint_level=hint_level,
        forbidden_disclosures=forbidden,
        required_evidence_ids=grounded,
        local_source_ids=local if hypothesis is None else [*local, hypothesis.id],
        expected_student_action=expected,
        drawing_actions=drawings,
        memory_hint=memory_hint,
        hypothesis=hypothesis,
        step_status=status,
        personality=persona.personality,
        comfort_override=persona.comfort_override,
        current_problem=current,
        representation=representation,
        support_change=support_change,
        reveal_allowed=reveal_allowed,
        decision_justification=justification,
    )
