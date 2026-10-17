"""The scaffold ladder: smaller steps, changed representations and explanation on request.

Support only changes when the learner's evidence changes. Each rung is a different way in,
never the same hint again, and the ladder is per attempt, so a fresh problem starts at the
lowest rung again (support fades). Explaining is a rung the learner can also ask for directly;
any explanation that shows a completed step is marked as a disclosure.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.pedagogy.intents import group_terms
from app.pedagogy.problems import GROUP_MARK_OFFSET, STATEMENT_X, STATEMENT_Y, ProblemSpec
from app.schemas.tutor import ActionType, Representation

EXPLAIN_LEVEL = 4
GROUPING_CONCEPT = "concept.grouping"
# Hint levels of the first rungs; the same number always means the same representation.
LEVEL_REPRESENTATION: dict[int, Representation] = {
    1: "outside_factor",
    2: "groups_picture",
    3: "number_case",
}

Source = Literal["not_sure", "explain_request", "partial_distribution"]
Trigger = Literal["requested", "repeated_difficulty"]


def next_level(levels: tuple[int, ...] | list[int]) -> int:
    """One rung above the highest hint already given in this attempt (1 when none)."""
    return 1 if not levels else min(max(levels) + 1, EXPLAIN_LEVEL)


@dataclass(frozen=True)
class ScaffoldMove:
    action: ActionType
    level: int
    representation: Representation
    params: dict[str, str]
    expected: str
    justification: str
    concepts: list[str]
    reveals: bool = False


def _number_case(spec: ProblemSpec) -> tuple[str, str]:
    terms = group_terms(spec)
    operator = "-" if spec.group_text is not None and "-" in spec.group_text else "+"
    second = terms[1] if len(terms) > 1 else "2"
    factor = spec.factor_text or "2"
    expression = f"{factor}*(1 {operator} {second}) = {factor}*1 {operator} {factor}*{second}"
    return expression, f"{factor}(1 {operator} {second})"


def choose_move(
    spec: ProblemSpec,
    *,
    source: Source,
    levels: tuple[int, ...],
    counter_evidence: bool,
) -> ScaffoldMove:
    """Pick the next rung from the hint levels already given in this attempt.

    Counter-evidence against the first-term-only hypothesis (an earlier verified full
    distribution) replaces the escalation with a gentler copy check, because a slip is the
    more plausible alternative then.
    """
    base_params = {
        "factor": spec.factor_text or "",
        "group": spec.group_text or "",
        "source": source,
    }
    concepts = [spec.step_concept_id]
    explained_before = EXPLAIN_LEVEL in levels
    level = next_level(levels)
    if source == "explain_request" or (level >= EXPLAIN_LEVEL and not explained_before):
        trigger: Trigger = "requested" if source == "explain_request" else "repeated_difficulty"
        return ScaffoldMove(
            action="explain_on_request",
            level=EXPLAIN_LEVEL,
            representation="worked_step",
            params={
                **base_params,
                "trigger": trigger,
                "kind": spec.kind,
                "expanded": spec.expanded_step or "",
            },
            expected=(
                f"Type your next step, starting from {spec.expanded_step}."
                if spec.expanded_step
                else "Say it back in your own words: why does the second term get multiplied too?"
            ),
            justification=(
                "Learner asked to be told, so give a short explanation and a next action."
                if trigger == "requested"
                else "Several scaffolds have not unlocked it, so explain and return the next step."
            ),
            concepts=concepts,
            reveals=True,
        )
    if explained_before:
        return ScaffoldMove(
            action="smaller_scaffold",
            level=EXPLAIN_LEVEL,
            representation="next_step",
            params={**base_params, "expanded": spec.expanded_step or ""},
            expected="Type what you would do to both sides next.",
            justification="The step was already explained, so shrink the ask to one operation.",
            concepts=concepts,
        )
    if counter_evidence and source == "partial_distribution":
        return ScaffoldMove(
            action="diagnostic_hint",
            level=max(levels, default=1),
            representation="copy_check",
            params=base_params,
            expected="Compare your line with the problem and rewrite it.",
            justification=(
                "An earlier verified step spread the factor over both terms, so a copying "
                "slip is likely; check before reteaching."
            ),
            concepts=concepts,
        )
    representation = LEVEL_REPRESENTATION[level]
    params = dict(base_params)
    if representation == "number_case":
        concepts = [spec.step_concept_id, GROUPING_CONCEPT]
        _, phrase = _number_case(spec)
        params["number_case"] = phrase
    if representation == "outside_factor":
        action: ActionType = "smaller_scaffold" if source == "not_sure" else "diagnostic_hint"
        expected = (
            "Type your best first step, or say 'just tell me' for an explanation."
            if source == "not_sure"
            else "Rewrite the left side so the outside factor reaches every term."
        )
        why = (
            "Learner is unsure, so shrink the task to one question about the outside factor."
            if source == "not_sure"
            else "Step is not equivalent and fits only the first term being multiplied; "
            "ask about both terms (tentative, a copying slip is possible)."
        )
    else:
        action = "change_representation"
        expected = (
            "Try the number case, then type a step for your problem."
            if representation == "number_case"
            else "Look at the groups on the board, then type your next step."
        )
        why = (
            "The earlier hint did not unlock it, so revisit the multiplication and grouping "
            "idea with small numbers."
            if representation == "number_case"
            else "The first hint did not unlock it, so show the groups instead of repeating it."
        )
    return ScaffoldMove(
        action=action,
        level=level,
        representation=representation,
        params=params,
        expected=expected,
        justification=why,
        concepts=concepts,
    )


def representation_drawings(
    spec: ProblemSpec, representation: Representation, statement_object_id: str | None
) -> list[dict[str, Any]]:
    """Deterministic board marks for a representation (never freehand geometry)."""
    span = spec.group_span()
    if statement_object_id is None or span is None or spec.group_text is None:
        return []
    start, end = span
    bracket_y = STATEMENT_Y + GROUP_MARK_OFFSET
    mark: list[dict[str, Any]] = [
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
            "start": {"x": start, "y": bracket_y},
            "end": {"x": end, "y": bracket_y},
        },
    ]
    picture_y = STATEMENT_Y + 90.0
    match representation:
        case "outside_factor" | "copy_check":
            return mark
        case "groups_picture" | "worked_step":
            factor = spec.factor_text or ""
            count = int(factor) if factor.isdigit() else 0
            if not 2 <= count <= 4:
                return mark
            groups = " + ".join([spec.group_text] * count)
            return [
                *mark,
                {
                    "tool": "add_math",
                    "semantic_role": "annotation",
                    "at": {"x": STATEMENT_X, "y": picture_y},
                    "text": groups,
                },
            ]
        case "number_case":
            expression, _ = _number_case(spec)
            return [
                {
                    "tool": "add_math",
                    "semantic_role": "annotation",
                    "at": {"x": STATEMENT_X, "y": picture_y},
                    "text": expression,
                }
            ]
        case _:
            return []
