"""The history-grounded tutoring evaluation: replay cutoffs, rubric, latency and honesty.

Everything here is local. The fixture candidates are scripted text, so no result below says
anything about a trained model, and no latency is invented for them.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.tutoring_eval.candidates import (
    Candidate,
    CandidateError,
    fixture_candidate,
    responses_file_candidate,
)
from app.tutoring_eval.cases import CASE_SET_VERSION, build_fixture_cases
from app.tutoring_eval.contracts import (
    DIMENSIONS,
    CandidateResponse,
    HistoryEvent,
    JudgeRating,
    ReplayCase,
    ReplaySnapshot,
    ReplayTurn,
    TurnExpectation,
)
from app.tutoring_eval.replay import build_snapshots, rubric_context, snapshot_for_turn
from app.tutoring_eval.rubric import (
    score_dimension,
    score_disclosure,
    score_hint_specificity,
    score_latency,
    score_math,
    score_memory_grounding,
    score_respect,
)
from app.tutoring_eval.runner import evaluate_candidate, run_judge, score_response

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _case(events: list[HistoryEvent], turn_minute: int = 30) -> ReplayCase:
    return ReplayCase(
        case_id="case.unit",
        title="Unit case",
        scenario="unit",
        history=events,
        turns=[
            ReplayTurn(
                turn_id="turn.unit.1",
                occurred_at=T0 + timedelta(minutes=turn_minute),
                learner_message="Is it 2x + 3?",
                problem_statement="2(x + 3) = 14",
                expectation=TurnExpectation(),
            )
        ],
    )


def _event(source_id: str, minute: int) -> HistoryEvent:
    return HistoryEvent(
        source_id=source_id,
        occurred_at=T0 + timedelta(minutes=minute),
        kind="learner_message",
        text=f"event {source_id}",
    )


@pytest.fixture(scope="module")
def snapshots() -> list[ReplaySnapshot]:
    return build_snapshots(build_fixture_cases())


def _row(report, case_id: str, turn_id: str):  # type: ignore[no-untyped-def]
    return next(r for r in report.rows if (r.case_id, r.turn_id) == (case_id, turn_id))


# --- replay -----------------------------------------------------------------------------


def test_every_snapshot_excludes_events_at_or_after_its_cutoff(
    snapshots: list[ReplaySnapshot],
) -> None:
    assert snapshots
    for snapshot in snapshots:
        assert all(event.occurred_at < snapshot.cutoff for event in snapshot.history)
        assert not [i for i in snapshot.available_source_ids if i.startswith("future.")]


def test_future_evidence_is_counted_as_omitted_never_shown(
    snapshots: list[ReplaySnapshot],
) -> None:
    by_turn = {s.turn_id: s for s in snapshots}
    first = by_turn["turn.pd.1"]
    assert first.omitted_future_events >= 1
    # A later turn in the same case sees only what happened before it, which is more.
    assert "hist.pd.4" not in first.available_source_ids
    assert "hist.pd.4" in by_turn["turn.pd.2"].available_source_ids


def test_source_ids_match_the_visible_history_exactly(snapshots: list[ReplaySnapshot]) -> None:
    for snapshot in snapshots:
        assert snapshot.available_source_ids == [e.source_id for e in snapshot.history]
        assert len(set(snapshot.available_source_ids)) == len(snapshot.available_source_ids)


def test_an_event_at_exactly_the_cutoff_is_not_yet_known() -> None:
    case = _case([_event("hist.a", 10), _event("hist.at-cutoff", 30), _event("hist.later", 31)])
    snapshot = snapshot_for_turn(case, case.turns[0])
    assert snapshot.available_source_ids == ["hist.a"]
    assert snapshot.omitted_future_events == 2


def test_history_bound_keeps_the_most_recent_events_and_counts_the_rest() -> None:
    case = _case([_event(f"hist.{n}", n) for n in range(1, 6)])
    snapshot = snapshot_for_turn(case, case.turns[0], max_history=2)
    assert snapshot.available_source_ids == ["hist.4", "hist.5"]
    assert snapshot.omitted_by_bound == 3
    assert snapshot_for_turn(case, case.turns[0], max_history=0).history == []


def test_history_bound_outside_the_allowed_range_is_rejected() -> None:
    case = _case([_event("hist.1", 1)])
    with pytest.raises(ValueError, match="max_history"):
        snapshot_for_turn(case, case.turns[0], max_history=-1)
    with pytest.raises(ValueError, match="max_history"):
        snapshot_for_turn(case, case.turns[0], max_history=999)


def test_digest_covers_what_the_candidate_can_see() -> None:
    short = _case([_event("hist.1", 1)])
    longer = _case([_event("hist.1", 1), _event("hist.2", 2)])
    a = snapshot_for_turn(short, short.turns[0])
    assert a.digest == snapshot_for_turn(short, short.turns[0]).digest
    assert a.digest != snapshot_for_turn(longer, longer.turns[0]).digest
    # An event that is still in the future does not change what the candidate sees.
    with_future = _case([_event("hist.1", 1), _event("future.9", 90)])
    assert snapshot_for_turn(with_future, with_future.turns[0]).digest == a.digest


def test_a_duplicate_turn_is_rejected() -> None:
    case = _case([_event("hist.1", 1)])
    with pytest.raises(ValueError, match="duplicate turn"):
        build_snapshots([case, case])


def test_fixture_cases_are_fictional_and_versioned() -> None:
    cases = build_fixture_cases()
    assert CASE_SET_VERSION.startswith("tutoring-fixture-cases")
    assert len(cases) >= 7
    assert all(case.is_fictional for case in cases)


def test_rubric_context_carries_only_visible_ids_and_prior_tutor_text(
    snapshots: list[ReplaySnapshot],
) -> None:
    for snapshot in snapshots:
        context = rubric_context(snapshot)
        assert context["available_source_ids"] == snapshot.available_source_ids
        assert "future" not in json.dumps(context)


# --- rubric dimensions ------------------------------------------------------------------


def test_good_fixture_scores_every_applicable_dimension_fully(
    snapshots: list[ReplaySnapshot],
) -> None:
    report = evaluate_candidate(fixture_candidate("good"), snapshots)
    assert report.errors == 0
    for summary in report.dimensions:
        assert summary.scored_rows + summary.missing_rows == len(snapshots)
        assert summary.scored_rows > 0
        assert summary.mean == 1.0, summary.dimension


def test_leaky_fixture_is_caught_on_disclosure_and_respect(
    snapshots: list[ReplaySnapshot],
) -> None:
    report = evaluate_candidate(fixture_candidate("leaky"), snapshots)
    means = {s.dimension: s.mean for s in report.dimensions}
    assert means["disclosure"] is not None and means["disclosure"] < 0.5
    assert means["respect"] is not None and means["respect"] < 1.0
    assert means["hint_usefulness"] is not None and means["hint_usefulness"] < 1.0


def test_ungrounded_fixture_is_caught_on_memory_grounding(
    snapshots: list[ReplaySnapshot],
) -> None:
    report = evaluate_candidate(fixture_candidate("ungrounded"), snapshots)
    means = {s.dimension: s.mean for s in report.dimensions}
    assert means["memory_grounding"] is not None and means["memory_grounding"] < 0.5


def test_each_dimension_is_reported_separately_with_no_blended_total(
    snapshots: list[ReplaySnapshot],
) -> None:
    report = evaluate_candidate(fixture_candidate("good"), snapshots)
    assert [s.dimension for s in report.dimensions] == list(DIMENSIONS)
    dumped = report.model_dump(mode="json")
    assert "overall" not in dumped and "total_score" not in dumped
    for row in report.rows:
        assert [s.dimension for s in row.scores] == list(DIMENSIONS)


def test_math_penalizes_a_wrong_claim_and_rewards_a_true_one() -> None:
    context = {
        "expectation": {
            "wrong_claims": ["2(x+3)=2x+3"],
            "correct_claims": ["2(x+3)=2x+6"],
        }
    }
    wrong, _ = score_math("So 2(x + 3) = 2x + 3, right?", context)
    right, _ = score_math("Remember 2(x + 3) = 2x + 6.", context)
    assert wrong is not None and right is not None
    assert wrong < right == 1.0


def test_math_is_not_applicable_when_the_reply_makes_no_mathematical_claim() -> None:
    value, _ = score_math("Take your time.", {"expectation": {"correct_claims": ["x=4"]}})
    assert value is None


def test_disclosure_checks_the_reply_and_the_candidate_s_own_claim() -> None:
    context = {"expectation": {"answer_strings": ["x=4"], "allow_explanation": False}}
    hidden, _ = score_disclosure("What do you get after dividing both sides?", context, False)
    leaked, _ = score_disclosure("The answer is x = 4.", context, False)
    assert hidden == 1.0
    assert leaked is not None and leaked < 1.0


def test_respect_flags_blame() -> None:
    value, _ = score_respect("You should have seen that already.", {"expectation": {}})
    assert value is not None and value < 1.0


def test_specificity_wants_the_problem_s_own_terms() -> None:
    context = {"expectation": {"anchors": ["x + 3"], "expects_hint": True}}
    vague, _ = score_hint_specificity("Try thinking about it more carefully.", context)
    specific, _ = score_hint_specificity("What does the 2 multiply in x + 3?", context)
    assert vague is not None and specific is not None
    assert vague < specific


def test_memory_grounding_rejects_ids_that_were_not_shown() -> None:
    context = {
        "expectation": {"expected_memory_source_ids": ["hist.1"]},
        "available_source_ids": ["hist.1"],
    }
    grounded, _ = score_memory_grounding("As you said before...", context, ["hist.1"])
    invented, _ = score_memory_grounding("As you said before...", context, ["hist.fake"])
    assert grounded == 1.0
    assert invented == 0.0


def test_unknown_dimension_is_an_error_not_a_zero() -> None:
    with pytest.raises(ValueError, match="unknown rubric dimension"):
        score_dimension("charm", "hello", {})


def test_scores_are_finite_and_bounded(snapshots: list[ReplaySnapshot]) -> None:
    for name in ("good", "leaky", "ungrounded"):
        report = evaluate_candidate(fixture_candidate(name), snapshots)
        for row in report.rows:
            for score in row.scores:
                assert score.value is None or 0.0 <= score.value <= 1.0


# --- latency ----------------------------------------------------------------------------


def test_fixture_candidates_have_missing_latency_not_an_invented_one(
    snapshots: list[ReplaySnapshot],
) -> None:
    report = evaluate_candidate(fixture_candidate("good"), snapshots)
    assert report.latency_mean_ms is None
    assert report.latency_rows_missing == len(snapshots)
    for row in report.rows:
        assert row.latency_ms is None
        assert row.latency_source == "missing"
        assert row.latency_score is None


def test_a_measured_callable_records_its_own_call_time_and_scores_it() -> None:
    case = _case([_event("hist.1", 1)])
    snapshots = build_snapshots([case])
    ticks = iter([10.0, 10.5])

    def respond(snapshot: ReplaySnapshot) -> str:
        return "What does the 2 multiply in x + 3?"

    candidate = Candidate(name="callable:unit", label="callable", respond=respond)
    report = evaluate_candidate(
        candidate, snapshots, latency_budget_ms=1000.0, timer=lambda: next(ticks)
    )
    row = report.rows[0]
    assert row.latency_ms == pytest.approx(500.0)
    assert row.latency_source == "measured_local_call"
    assert row.latency_score == 1.0
    assert report.latency_mean_ms == pytest.approx(500.0)


def test_latency_score_falls_over_budget_and_is_missing_without_a_measurement() -> None:
    assert score_latency(None, 1000.0) is None
    assert score_latency(1000.0, 1000.0) == 1.0
    assert score_latency(1500.0, 1000.0) == pytest.approx(0.5)
    assert score_latency(5000.0, 1000.0) == 0.0


def test_responses_file_latency_is_recorded_as_supplied_and_absence_stays_missing(
    tmp_path: Path, snapshots: list[ReplaySnapshot]
) -> None:
    first, second = snapshots[0], snapshots[1]
    path = tmp_path / "replies.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": first.case_id,
                        "turn_id": first.turn_id,
                        "text": "What does the 2 outside x + 3 multiply?",
                        "latency_ms": 321.0,
                    }
                ),
                json.dumps(
                    {
                        "case_id": second.case_id,
                        "turn_id": second.turn_id,
                        "text": "What does each group of x + 3 hold?",
                    }
                ),
            ]
        )
    )
    candidate = responses_file_candidate(path)
    assert candidate.label == "external_responses"
    report = evaluate_candidate(candidate, [first, second])
    assert (report.rows[0].latency_ms, report.rows[0].latency_source) == (
        321.0,
        "supplied_by_candidate_source",
    )
    assert (report.rows[1].latency_ms, report.rows[1].latency_source) == (None, "missing")


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        json.dumps({"case_id": "c", "turn_id": "t"}),
        json.dumps({"case_id": "c", "turn_id": "t", "text": "hi", "latency_ms": -1}),
        json.dumps({"case_id": "c", "turn_id": "t", "text": "hi", "latency_ms": "fast"}),
        json.dumps({"case_id": "c", "turn_id": "t", "text": "hi", "latency_ms": True}),
    ],
)
def test_malformed_responses_files_are_rejected(tmp_path: Path, line: str) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(line)
    with pytest.raises(CandidateError, match="invalid responses file line 1"):
        responses_file_candidate(path)


# --- candidate failures, labels and claims ---------------------------------------------


def test_a_failing_candidate_row_is_sanitized_missing_and_does_not_stop_the_run() -> None:
    case = _case([_event("hist.1", 1)])
    snapshots = build_snapshots([case])

    def respond(snapshot: ReplaySnapshot) -> str:
        raise RuntimeError("upstream said Authorization: Bearer inert-canary-0123456789abcdef")

    report = evaluate_candidate(Candidate(name="c", label="callable", respond=respond), snapshots)
    row = report.rows[0]
    assert report.errors == 1
    assert row.response is None
    assert row.error is not None and "inert-canary" not in row.error
    assert row.latency_ms is None and row.latency_source == "missing"
    assert all(score.value is None for score in row.scores)


def test_fixture_candidates_are_labeled_and_a_report_claims_no_trained_model_or_gain(
    snapshots: list[ReplaySnapshot],
) -> None:
    for name in ("good", "leaky", "ungrounded"):
        candidate = fixture_candidate(name)
        assert candidate.label == "fixture" and candidate.name == f"fixture:{name}"
        claims = evaluate_candidate(candidate, snapshots).claims
        assert claims.trained_model_result is False
        assert claims.learning_gain_claim is False
        assert claims.judge_scores_included is False


def test_report_cannot_be_constructed_with_a_trained_model_claim() -> None:
    from pydantic import ValidationError

    from app.tutoring_eval.contracts import RunClaims

    with pytest.raises(ValidationError):
        RunClaims(trained_model_result=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RunClaims(learning_gain_claim=True)  # type: ignore[arg-type]


def test_an_unknown_fixture_candidate_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown fixture candidate"):
        fixture_candidate("trained-lora")


def test_score_response_matches_the_remote_scoring_entrypoint(
    snapshots: list[ReplaySnapshot],
) -> None:
    snapshot = snapshots[0]
    response = CandidateResponse(text="What does the 2 multiply in x + 3?")
    context = rubric_context(snapshot)
    for score in score_response(snapshot, response):
        expected, _ = score_dimension(score.dimension, response.text, context)
        assert score.value == expected


# --- judge ------------------------------------------------------------------------------


def test_judge_ratings_are_labeled_capped_and_never_merged_with_scores(
    snapshots: list[ReplaySnapshot],
) -> None:
    report = evaluate_candidate(fixture_candidate("good"), snapshots)
    before = report.model_dump(mode="json")
    calls: list[str] = []

    def judge(snapshot: ReplaySnapshot, response: CandidateResponse) -> JudgeRating:
        calls.append(snapshot.turn_id)
        if snapshot.turn_id == snapshots[1].turn_id:
            raise RuntimeError("judge failed")
        return JudgeRating(rating=0.5, rationale="fixture judge")

    summary = run_judge(judge, "fixture-judge", snapshots, report, max_rows=3)
    assert summary.kind == "model_judged"
    assert len(calls) == 3 and len(summary.rows) == 3
    assert summary.errors == 1
    assert summary.mean_rating == pytest.approx(0.5)
    assert report.model_dump(mode="json") == before
    assert report.claims.judge_scores_included is False


def test_judge_with_no_ratings_has_no_mean(snapshots: list[ReplaySnapshot]) -> None:
    report = evaluate_candidate(fixture_candidate("good"), snapshots)

    def judge(snapshot: ReplaySnapshot, response: CandidateResponse) -> JudgeRating:
        raise RuntimeError("down")

    summary = run_judge(judge, "j", snapshots, report, max_rows=2)
    assert summary.mean_rating is None and summary.errors == 2
