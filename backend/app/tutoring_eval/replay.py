"""Replay a case turn by turn, showing each turn only the history that came before it.

For a turn at time ``t`` the snapshot keeps events with ``occurred_at < t`` (an event at
exactly ``t`` is not yet known), takes the most recent ``max_history`` of them, and records
how many later events and how many bound-trimmed events were left out. The snapshot digest
covers everything a candidate can see, so a pinned dataset revision can be tied back to it.
"""

import hashlib
import json

from app.tutoring_eval.contracts import (
    DEFAULT_MAX_HISTORY,
    MAX_HISTORY_LIMIT,
    ReplayCase,
    ReplaySnapshot,
    ReplayTurn,
)


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def snapshot_for_turn(
    case: ReplayCase, turn: ReplayTurn, max_history: int = DEFAULT_MAX_HISTORY
) -> ReplaySnapshot:
    if not 0 <= max_history <= MAX_HISTORY_LIMIT:
        raise ValueError(f"max_history must be between 0 and {MAX_HISTORY_LIMIT}")
    # Sort by time then ID so equal timestamps order deterministically.
    ordered = sorted(case.history, key=lambda event: (event.occurred_at, event.source_id))
    known = [event for event in ordered if event.occurred_at < turn.occurred_at]
    future = len(ordered) - len(known)
    visible = known[len(known) - max_history :] if max_history else []
    source_ids = [event.source_id for event in visible]
    visible_payload = [event.model_dump(mode="json") for event in visible]
    digest = _digest(
        {
            "case": case.case_id,
            "turn": turn.turn_id,
            "cutoff": turn.occurred_at.isoformat(),
            "message": turn.learner_message,
            "problem": turn.problem_statement,
            "history": visible_payload,
            "expectation": turn.expectation.model_dump(mode="json"),
        }
    )
    return ReplaySnapshot(
        case_id=case.case_id,
        turn_id=turn.turn_id,
        scenario=case.scenario,
        cutoff=turn.occurred_at,
        learner_message=turn.learner_message,
        problem_statement=turn.problem_statement,
        history=visible,
        available_source_ids=source_ids,
        omitted_future_events=future,
        omitted_by_bound=len(known) - len(visible),
        expectation=turn.expectation,
        digest=digest,
    )


def build_snapshots(
    cases: list[ReplayCase], max_history: int = DEFAULT_MAX_HISTORY
) -> list[ReplaySnapshot]:
    seen: set[tuple[str, str]] = set()
    snapshots: list[ReplaySnapshot] = []
    for case in cases:
        for turn in sorted(case.turns, key=lambda t: t.occurred_at):
            key = (case.case_id, turn.turn_id)
            if key in seen:
                raise ValueError(f"duplicate turn {turn.turn_id} in case {case.case_id}")
            seen.add(key)
            snapshots.append(snapshot_for_turn(case, turn, max_history))
    return snapshots


def rubric_context(snapshot: ReplaySnapshot) -> dict[str, object]:
    """The plain mapping the rubric scores against (also what a Chalk scorer receives)."""
    return {
        "expectation": snapshot.expectation.model_dump(mode="json"),
        "available_source_ids": list(snapshot.available_source_ids),
        "prior_tutor_texts": [e.text for e in snapshot.history if e.kind == "tutor_hint"],
    }
