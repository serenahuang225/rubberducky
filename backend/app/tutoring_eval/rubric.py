"""Deterministic tutoring rubric: pure functions over plain strings and mappings.

This module imports only the standard library so the same code can run locally and, when a
Chalk evaluation is explicitly started, inside a deployed scorer. Each dimension is scored
separately in [0, 1]. ``None`` means the dimension does not apply to the turn (or could not
be measured); it is never converted to a zero or a one, and dimensions are never blended
into one number.

These are surface checks on wording. They do not judge whether an explanation is good, so a
reply can pass every score here and still teach badly. Model-judged ratings are separate.
"""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

RUBRIC_VERSION = "tutoring-rubric.v1"

ScoreResult = tuple[float | None, str]

_ARITHMETIC = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*([+\-*/\u00d7\u00f7])\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)(?![\w.])"
)
_QUESTION_LEAD = re.compile(
    r"\b(what|how|why|which|can you|could you|do you|does|would you|where)\b", re.IGNORECASE
)
_ACTION_LEAD = re.compile(
    r"\b(try|look|write|circle|compare|notice|check|tell me|show me|draw|pick|think about|"
    r"say what)\b",
    re.IGNORECASE,
)
_PAST_CLAIM = re.compile(
    r"\b(last time|earlier you|you told me|you said|before, you|as you mentioned|"
    r"i remember|we did)\b",
    re.IGNORECASE,
)
_ACKNOWLEDGE = re.compile(
    r"\b(tired|no rush|take your time|that's okay|that's ok|that is okay|it's okay|"
    r"it's ok|totally fine|sounds like|that sounds|slower|lighter|short one|one small)\b",
    re.IGNORECASE,
)
# Blame, fixed labels, and inferred emotion or disability. The tutor may offer a choice but
# must not state any of these about the learner.
_DISRESPECT: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "blame",
        re.compile(
            r"\b(you (should have|always|never)|your fault|careless|lazy|not trying|"
            r"obviously|as i already (said|told))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "label",
        re.compile(
            r"\b(you are|you're|you must be) (bad|slow|dumb|stupid|a visual learner|"
            r"an auditory learner|not a math person)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "inferred_state",
        re.compile(
            r"\b(you must be|you seem|you are clearly|you're clearly) "
            r"(frustrated|angry|upset|anxious|bored)\b|"
            r"\b(dyscalculia|adhd|dyslexia|learning disability)\b",
            re.IGNORECASE,
        ),
    ),
)
_WORD = re.compile(r"[A-Za-z0-9']+")


def squash(text: str) -> str:
    """Lowercase with all whitespace removed, so "2x + 3" and "2x+3" compare equal."""
    return re.sub(r"\s+", "", text).lower()


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _as_strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str)]


def _expectation(context: Mapping[str, object]) -> Mapping[str, object]:
    expectation = context.get("expectation")
    return expectation if isinstance(expectation, Mapping) else {}


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _arithmetic_holds(left: Decimal, op: str, right: Decimal, result: Decimal) -> bool | None:
    if op == "+":
        return left + right == result
    if op == "-":
        return left - right == result
    if op in "*\u00d7":
        return left * right == result
    if right == 0:
        return None
    return left / right == result


def score_math(text: str, context: Mapping[str, object]) -> ScoreResult:
    """Fraction of checkable mathematical statements that are correct.

    Checks simple ``a op b = c`` arithmetic and the case's known statements: a known-wrong
    claim (for instance an incomplete distribution) counts as wrong, a known-true one as
    correct. Replies that make no checkable statement are not scored.
    """
    squashed = squash(text)
    wrong_claims = _as_strings(_expectation(context).get("wrong_claims"))
    wrong = sum(1 for claim in wrong_claims if squash(claim) in squashed)
    right_claims = _as_strings(_expectation(context).get("correct_claims"))
    correct = sum(1 for claim in right_claims if squash(claim) in squashed)
    for match in _ARITHMETIC.finditer(text):
        left, right, result = (_decimal(match.group(i)) for i in (1, 3, 4))
        if left is None or right is None or result is None:
            continue
        holds = _arithmetic_holds(left, match.group(2), right, result)
        if holds is None:
            continue
        if holds:
            correct += 1
        else:
            wrong += 1
    checked = correct + wrong
    if checked == 0:
        return None, "no checkable mathematical statement"
    return correct / checked, f"{correct} correct, {wrong} wrong of {checked} checked"


def score_diagnosis(text: str, context: Mapping[str, object]) -> ScoreResult:
    """Half for asking a question, half for covering each diagnostic cue group."""
    groups = _expectation(context).get("diagnostic_cues")
    if not isinstance(groups, Sequence) or not groups:
        return None, "turn does not call for a diagnostic question"
    lowered = text.lower()
    squashed = squash(text)
    covered = 0
    total = 0
    for group in groups:
        cues = _as_strings(group)
        if not cues:
            continue
        total += 1
        if any(cue.lower() in lowered or squash(cue) in squashed for cue in cues):
            covered += 1
    if total == 0:
        return None, "turn does not call for a diagnostic question"
    asks = "?" in text
    value = 0.5 * (1.0 if asks else 0.0) + 0.5 * covered / total
    return value, f"question={'yes' if asks else 'no'}, cue groups {covered}/{total}"


def revealed_answer(text: str, context: Mapping[str, object]) -> bool:
    squashed = squash(text)
    answers = _as_strings(_expectation(context).get("answer_strings"))
    return any(squash(answer) in squashed for answer in answers if answer.strip())


def score_disclosure(
    text: str, context: Mapping[str, object], claimed_revealed: bool | None
) -> ScoreResult:
    """1.0 for withholding what must stay hidden, or for disclosing only as asked and labeled."""
    expectation = _expectation(context)
    if not _as_strings(expectation.get("answer_strings")):
        return None, "turn has no answer to withhold"
    actual = revealed_answer(text, context)
    if expectation.get("allow_explanation") is True:
        # An explanation was requested, so disclosure is allowed but must be labeled.
        if not actual:
            return 1.0, "explained without a completed step"
        if claimed_revealed is True:
            return 1.0, "disclosed on request and labeled answer_revealed"
        return 0.0, "disclosed on request but not labeled answer_revealed"
    if actual:
        return 0.0, "revealed a withheld answer or completed step"
    return 1.0, "withheld the answer and completed step"


def score_hint_specificity(text: str, context: Mapping[str, object]) -> ScoreResult:
    """Fraction of the problem's own terms the reply refers to."""
    anchors = [a for a in _as_strings(_expectation(context).get("anchors")) if a.strip()]
    if not anchors:
        return None, "turn has no case-specific anchors"
    lowered = text.lower()
    squashed = squash(text)
    hit = sum(1 for a in anchors if a.lower() in lowered or squash(a) in squashed)
    return hit / len(anchors), f"{hit}/{len(anchors)} anchors referenced"


def _token_overlap(left: str, right: str) -> float:
    a, b = set(_words(left)), set(_words(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_hint_usefulness(text: str, context: Mapping[str, object]) -> ScoreResult:
    """Mean of: gives the learner something to do, stays short, and is not a repeated hint."""
    expectation = _expectation(context)
    if expectation.get("expects_hint") is not True:
        return None, "turn does not expect a hint"
    raw_max = expectation.get("max_words")
    max_words = raw_max if isinstance(raw_max, int) and raw_max > 0 else 60
    actionable = bool("?" in text or _QUESTION_LEAD.search(text) or _ACTION_LEAD.search(text))
    concise = len(_words(text)) <= max_words
    prior = _as_strings(context.get("prior_tutor_texts"))
    fresh = all(_token_overlap(text, earlier) < 0.8 for earlier in prior)
    parts = (actionable, concise, fresh)
    return (
        sum(parts) / len(parts),
        f"actionable={actionable}, concise={concise}, not_repeated={fresh}",
    )


def score_respect(text: str, context: Mapping[str, object]) -> ScoreResult:
    """Starts at 1.0, loses 0.5 per blame, label or inferred-state category, and is capped at
    0.5 when the learner's stated state called for acknowledgement and got none."""
    hits = [name for name, pattern in _DISRESPECT if pattern.search(text)]
    value = max(0.0, 1.0 - 0.5 * len(hits))
    detail = "no blame, labels or inferred state" if not hits else "found: " + ", ".join(hits)
    if _expectation(context).get("acknowledge_state") is True and not _ACKNOWLEDGE.search(text):
        value = min(value, 0.5)
        detail += "; learner's stated state not acknowledged"
    return value, detail


def score_memory_grounding(
    text: str, context: Mapping[str, object], cited_source_ids: Sequence[str]
) -> ScoreResult:
    """Citations must be IDs the replay actually showed; required ones should be present.

    Citing an ID outside the snapshot (including a future event) or referring to the past
    with no citation scores 0.
    """
    available = set(_as_strings(context.get("available_source_ids")))
    expected = _as_strings(_expectation(context).get("expected_memory_source_ids"))
    cited = list(dict.fromkeys(cited_source_ids))
    unknown = [source for source in cited if source not in available]
    if unknown:
        return 0.0, "cited a source not in the replayed history: " + ", ".join(unknown)
    if _PAST_CLAIM.search(text) and not cited:
        return 0.0, "refers to earlier sessions without citing a source"
    if expected:
        covered = sum(1 for source in expected if source in cited)
        return covered / len(expected), f"cited {covered}/{len(expected)} expected sources"
    if cited:
        return 1.0, "cited only replayed sources"
    return None, "no memory expected or used"


def score_latency(latency_ms: float | None, budget_ms: float) -> float | None:
    """1.0 within budget, falling linearly to 0.0 at twice the budget; None when unmeasured."""
    if latency_ms is None or budget_ms <= 0:
        return None
    if latency_ms <= budget_ms:
        return 1.0
    return max(0.0, 1.0 - (latency_ms - budget_ms) / budget_ms)


def score_dimension(
    dimension: str,
    text: str,
    context: Mapping[str, object],
    *,
    cited_source_ids: Sequence[str] = (),
    claimed_revealed: bool | None = None,
) -> ScoreResult:
    if dimension == "math":
        return score_math(text, context)
    if dimension == "diagnosis":
        return score_diagnosis(text, context)
    if dimension == "disclosure":
        return score_disclosure(text, context, claimed_revealed)
    if dimension == "hint_specificity":
        return score_hint_specificity(text, context)
    if dimension == "hint_usefulness":
        return score_hint_usefulness(text, context)
    if dimension == "respect":
        return score_respect(text, context)
    if dimension == "memory_grounding":
        return score_memory_grounding(text, context, cited_source_ids)
    raise ValueError(f"unknown rubric dimension: {dimension}")
