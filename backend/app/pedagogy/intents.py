"""Small deterministic readers for learner text that is not a mathematical step.

Everything here is a bounded, inspectable inference over the learner's own words. A match
changes which teaching move is chosen; it is never a diagnosis and never changes what the
verifier says about a value.
"""

import re
from typing import Literal

from app.pedagogy.problems import ProblemSpec
from app.verification import assess_input

HelpIntent = Literal["not_sure", "explain_request"]

MAX_INTENT_CHARS = 120

_EXPLAIN = re.compile(
    r"\b(just\s+tell\s+me|tell\s+me\s+(the\s+)?(answer|how|why|what)|show\s+me\s+how"
    r"|explain\s+(it|this|that)(\s+to\s+me)?|give\s+me\s+the\s+(answer|solution)"
    r"|walk\s+me\s+through)\b"
)
_NOT_SURE = re.compile(
    r"\b(i\s+(do\s*not|don'?t|dont)\s+know|idk|no\s+idea|not\s+sure|i\s*'?m\s+(stuck|lost|confused)"
    r"|i\s+am\s+(stuck|lost|confused)|help(\s+me)?|stuck)\b"
)


def _tidy(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").split())


def help_intent(text: str) -> HelpIntent | None:
    """Read a short message as a request to be told (``explain_request``) or as not knowing.

    An explicit request to be told wins over "I don't know", so "I don't know, just tell me"
    is honored as a request for explanation.
    """
    if len(text) > MAX_INTENT_CHARS:
        return None
    tidy = _tidy(text)
    if _EXPLAIN.search(tidy):
        return "explain_request"
    if _NOT_SURE.search(tidy):
        return "not_sure"
    return None


# A bare minus or an opening parenthesis is also arithmetic, so only a dash glyph or a
# parenthesis that opens a word can start the learner's explanation.
_SEPARATOR = re.compile(
    r"\s*(?:\bbecause\b|\bsince\b|\bbut\b|\bso\b|[;,:\u2013\u2014]|\.(?=\s|$)"
    r"|\s\((?=[A-Za-z]{3,}\b))\s*"
)


def split_claim_and_reasoning(text: str) -> tuple[str, str | None]:
    """Separate a leading mathematical claim from trailing words about the method.

    The claim part must itself parse as a bounded mathematical input; otherwise the text is
    returned whole. The remainder is only ever read by the reasoning reader below.
    """
    for match in _SEPARATOR.finditer(text):
        claim = text[: match.start()].strip()
        rest = text[match.end() :].strip().rstrip(")").strip(" .")
        if claim and rest and assess_input(claim)[0].status == "parsed":
            return claim, rest
    return text.strip(), None


_NUMBER_WORDS = {
    "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
    "7": "seven", "8": "eight", "9": "nine", "10": "ten", "11": "eleven", "12": "twelve",
}  # fmt: skip

SECOND_TERM_UNCHANGED = "second_term_unchanged"
FIRST_TERM_ONLY = "first_term_only"
# A keyword reading of free text is weak evidence, so confidence stays low.
REASONING_CONFIDENCE = 0.5


def group_terms(spec: ProblemSpec) -> list[str]:
    if spec.group_text is None:
        return []
    inner = spec.group_text.strip("() ")
    return [term for term in re.split(r"\s*[+-]\s*", inner) if term]


def _alternatives(term: str) -> str:
    word = _NUMBER_WORDS.get(term)
    options = [re.escape(term), *([re.escape(word)] if word else [])]
    return "|".join(options)


def questionable_reasoning(spec: ProblemSpec, reasoning: str | None) -> str | None:
    """Name the questionable-method pattern the learner's own words describe, if any.

    Recognizes a stated method that skips the second term inside the parentheses, for
    example "I multiplied 2 by x but left 3 unchanged". Returns ``None`` when the words
    do not describe such a method; that is not evidence the method was sound.
    """
    terms = group_terms(spec)
    if reasoning is None or len(terms) < 2:
        return None
    tidy = _tidy(reasoning)
    first = _alternatives(terms[0])
    second = "|".join(_alternatives(term) for term in terms[1:]) + r"|second term|other term"
    gap = r"[^.;,]{0,24}"
    skip_second = (
        rf"\b(left|leave|leaving|kept|keep|keeping|ignored|ignore|skipped|skip|forgot){gap}"
        rf"\b({second})\b",
        rf"\b(didn'?t|did not|never|not|without|forgot to){gap}\b(multipl\w*|times|distribut\w*)"
        rf"{gap}\b({second})\b",
        rf"\b({second})\b{gap}\b(unchanged|stays|stayed|same|alone|as is)\b",
    )
    if any(re.search(pattern, tidy) for pattern in skip_second):
        return SECOND_TERM_UNCHANGED
    only_first = (
        rf"\b(only|just){gap}\b(multipl\w*|times){gap}\b({first}|first)\b",
        rf"\bmultipl\w*{gap}\b(only|just){gap}\b({first}|first)\b",
    )
    if any(re.search(pattern, tidy) for pattern in only_first):
        return FIRST_TERM_ONLY
    return None
