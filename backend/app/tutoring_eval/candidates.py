"""The candidate boundary: any callable from a replay snapshot to a tutor reply.

A candidate can be a deterministic fixture, a live provider wrapped by the caller, or
precomputed responses supplied by another pipeline. The evaluator needs nothing else, so it
does not depend on how a model was trained or served. Fixture candidates are scripted text,
labeled ``fixture``; they exercise the rubric and say nothing about any model.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.tutoring_eval.contracts import CandidateResponse, ReplaySnapshot

CandidateCallable = Callable[[ReplaySnapshot], CandidateResponse | str]
CandidateLabel = Literal["fixture", "external_responses", "callable"]

MAX_RESPONSES_FILE_BYTES = 2_000_000


class CandidateError(Exception):
    """A candidate could not produce a reply for this row."""


@dataclass(frozen=True)
class Candidate:
    name: str
    label: CandidateLabel
    respond: CandidateCallable
    # False when calling ``respond`` is only a lookup, so its wall time says nothing about the
    # model that produced the text.
    measures_latency: bool = True
    # Latency reported by whoever produced the text; recorded as supplied, never as measured.
    supplied_latency_ms: Mapping[tuple[str, str], float] | None = None


_GOOD: dict[str, tuple[str, list[str]]] = {
    "turn.pd.1": (
        "Let's look at your line together. What does the 2 outside multiply in 2(x + 3): "
        "just the x, or both terms?",
        [],
    ),
    "turn.pd.2": (
        "Think of 2(x + 3) as 2 groups of x + 3. What does each group hold, and how many 3s "
        "is that altogether?",
        ["hist.pd.4"],
    ),
    "turn.rw.1": (
        "Nice, x = 4 does check out. How did you get to 4? Walk me through what you tried.",
        ["hist.rw.2"],
    ),
    "turn.jt.1": (
        "That sounds frustrating, and it's okay. Let's make it smaller: what is inside the "
        "bracket that the 2 needs to reach? Just name the two terms.",
        [],
    ),
    "turn.jt.2": (
        "Sure. Picture 2 groups of (x + 3): that's 2x + 6 = 14. Each group has an x and a 3, "
        "so the 2 reaches both terms. Now can you say what 2x equals?",
        ["hist.jt.3"],
    ),
    "turn.ti.1": (
        "Thanks for telling me you're tired. Let's keep it light, just one small step: what "
        "is the 2 multiplying inside the bracket?",
        ["hist.ti.1"],
    ),
    "turn.ah.1": (
        "I can't read that line clearly. Is that 2x + 3 or 2x + 8? Please confirm or type it, "
        "and then we'll go on.",
        ["hist.ah.1"],
    ),
    "turn.as.1": (
        "Yes, 2x + 6 = 14, and the groups picture helped you get the 2 onto both terms. Want to "
        "try a new problem like it, without the picture?",
        ["hist.as.1"],
    ),
    "turn.si.1": (
        "No rush. Here is a quiet nudge using your picture: 2 groups of x + 3. What is in "
        "one group?",
        ["hist.si.1"],
    ),
}


def fixture_good(snapshot: ReplaySnapshot) -> CandidateResponse:
    try:
        text, cited = _GOOD[snapshot.turn_id]
    except KeyError as error:
        raise CandidateError(f"no scripted reply for {snapshot.turn_id}") from error
    # The explanation turn deliberately shows the completed step and says so.
    revealed = snapshot.turn_id == "turn.jt.2"
    return CandidateResponse(text=text, cited_source_ids=cited, answer_revealed=revealed)


def fixture_leaky(snapshot: ReplaySnapshot) -> CandidateResponse:
    """Hands over the answer, blames the learner and claims it withheld nothing."""
    answers = snapshot.expectation.answer_strings
    reveal = answers[-1] if answers else "just copy the line"
    return CandidateResponse(
        text=f"Obviously the answer is {reveal}. You should have seen that already.",
        cited_source_ids=[],
        answer_revealed=False,
    )


def fixture_ungrounded(snapshot: ReplaySnapshot) -> CandidateResponse:
    """Remembers things it was never shown and cites a source that does not exist."""
    return CandidateResponse(
        text="Last time you told me you hate fractions, so let's skip this one.",
        cited_source_ids=["hist.invented.0"],
        answer_revealed=False,
    )


FIXTURE_CANDIDATES: dict[str, CandidateCallable] = {
    "good": fixture_good,
    "leaky": fixture_leaky,
    "ungrounded": fixture_ungrounded,
}


def fixture_candidate(name: str) -> Candidate:
    try:
        respond = FIXTURE_CANDIDATES[name]
    except KeyError as error:
        raise ValueError(f"unknown fixture candidate: {name}") from error
    # Scripted text takes no model time, so timing it would invent a latency.
    return Candidate(
        name=f"fixture:{name}", label="fixture", respond=respond, measures_latency=False
    )


def responses_file_candidate(path: Path, *, name: str | None = None) -> Candidate:
    """Candidate backed by a JSONL file of precomputed replies from another pipeline.

    Each line has ``case_id``, ``turn_id`` and ``text``; ``cited_source_ids``,
    ``answer_revealed`` and ``latency_ms`` are optional. A supplied latency is recorded as
    supplied by the source, and an absent one stays missing.
    """
    if path.stat().st_size > MAX_RESPONSES_FILE_BYTES:
        raise CandidateError("responses file is too large")
    replies: dict[tuple[str, str], CandidateResponse] = {}
    latencies: dict[tuple[str, str], float] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            key = (str(raw["case_id"]), str(raw["turn_id"]))
            reply = CandidateResponse(
                text=raw["text"],
                cited_source_ids=raw.get("cited_source_ids", []),
                answer_revealed=raw.get("answer_revealed"),
            )
            latency = raw.get("latency_ms")
            if latency is not None:
                if isinstance(latency, bool) or not isinstance(latency, int | float):
                    raise ValueError("latency_ms must be a number")
                if not 0 <= latency < float("inf"):
                    raise ValueError("latency_ms must be finite and non-negative")
                latencies[key] = float(latency)
        except (KeyError, ValueError, TypeError, ValidationError) as error:
            raise CandidateError(f"invalid responses file line {number}") from error
        replies[key] = reply

    def respond(snapshot: ReplaySnapshot) -> CandidateResponse:
        try:
            return replies[(snapshot.case_id, snapshot.turn_id)]
        except KeyError as error:
            raise CandidateError("no supplied response for this turn") from error

    return Candidate(
        name=name or f"responses:{path.name}",
        label="external_responses",
        respond=respond,
        measures_latency=False,
        supplied_latency_ms=latencies,
    )
