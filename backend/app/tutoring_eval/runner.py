"""Run a candidate over replay snapshots and score each reply with the deterministic rubric.

Latency is wall time around the candidate callable, measured here with a monotonic clock.
It is the cost of that local call only. When a candidate only looks text up, or the call
failed, latency stays missing rather than becoming a number.
"""

import time
from collections.abc import Callable, Sequence

from app.redaction import redact_text
from app.tutoring_eval.candidates import Candidate
from app.tutoring_eval.contracts import (
    DIMENSIONS,
    CandidateResponse,
    Dimension,
    DimensionScore,
    DimensionSummary,
    EvaluationReport,
    JudgedRow,
    JudgedSummary,
    JudgeRating,
    LatencySource,
    ReplaySnapshot,
    RowResult,
    RunClaims,
)
from app.tutoring_eval.replay import rubric_context
from app.tutoring_eval.rubric import RUBRIC_VERSION, score_dimension, score_latency

DEFAULT_LATENCY_BUDGET_MS = 2_000.0
MAX_ERROR_CHARS = 160

Timer = Callable[[], float]
Judge = Callable[[ReplaySnapshot, CandidateResponse], JudgeRating]


def _sanitized(error: BaseException) -> str:
    # Candidate errors can echo prompts or credentials, so only the type and a short,
    # single-line message survive into a report.
    message = " ".join(redact_text(str(error)).split())[:MAX_ERROR_CHARS]
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def score_response(snapshot: ReplaySnapshot, response: CandidateResponse) -> list[DimensionScore]:
    context = rubric_context(snapshot)
    scores: list[DimensionScore] = []
    for name in DIMENSIONS:
        value, detail = score_dimension(
            name,
            response.text,
            context,
            cited_source_ids=response.cited_source_ids,
            claimed_revealed=response.answer_revealed,
        )
        dimension: Dimension = name  # type: ignore[assignment]
        scores.append(DimensionScore(dimension=dimension, value=value, detail=detail))
    return scores


def _missing_scores(reason: str) -> list[DimensionScore]:
    return [
        DimensionScore(dimension=name, value=None, detail=reason)  # type: ignore[arg-type]
        for name in DIMENSIONS
    ]


def _normalize(raw: CandidateResponse | str) -> CandidateResponse:
    return raw if isinstance(raw, CandidateResponse) else CandidateResponse(text=raw)


def _latency(
    candidate: Candidate, snapshot: ReplaySnapshot, measured_ms: float | None
) -> tuple[float | None, LatencySource]:
    if candidate.measures_latency and measured_ms is not None:
        return measured_ms, "measured_local_call"
    supplied = (candidate.supplied_latency_ms or {}).get((snapshot.case_id, snapshot.turn_id))
    if supplied is not None:
        return supplied, "supplied_by_candidate_source"
    return None, "missing"


def evaluate_candidate(
    candidate: Candidate,
    snapshots: Sequence[ReplaySnapshot],
    *,
    latency_budget_ms: float = DEFAULT_LATENCY_BUDGET_MS,
    timer: Timer = time.perf_counter,
) -> EvaluationReport:
    rows: list[RowResult] = []
    for snapshot in snapshots:
        response: CandidateResponse | None = None
        error: str | None = None
        measured_ms: float | None = None
        started = timer()
        try:
            response = _normalize(candidate.respond(snapshot))
            measured_ms = max(0.0, (timer() - started) * 1000.0)
        except Exception as caught:
            error = _sanitized(caught)
        latency_ms, source = _latency(candidate, snapshot, measured_ms if error is None else None)
        rows.append(
            RowResult(
                case_id=snapshot.case_id,
                turn_id=snapshot.turn_id,
                scenario=snapshot.scenario,
                snapshot_digest=snapshot.digest,
                response=response,
                error=error,
                scores=(
                    score_response(snapshot, response)
                    if response is not None
                    else _missing_scores("candidate produced no reply")
                ),
                latency_ms=latency_ms,
                latency_source=source,
                latency_score=score_latency(latency_ms, latency_budget_ms),
            )
        )
    return _report(candidate, rows, latency_budget_ms)


def _report(candidate: Candidate, rows: list[RowResult], budget_ms: float) -> EvaluationReport:
    summaries: list[DimensionSummary] = []
    for name in DIMENSIONS:
        values = [
            score.value
            for row in rows
            for score in row.scores
            if score.dimension == name and score.value is not None
        ]
        summaries.append(
            DimensionSummary(
                dimension=name,
                mean=sum(values) / len(values) if values else None,
                scored_rows=len(values),
                missing_rows=len(rows) - len(values),
            )
        )
    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    return EvaluationReport(
        rubric_version=RUBRIC_VERSION,
        candidate_name=candidate.name,
        candidate_label=candidate.label,
        latency_budget_ms=budget_ms,
        rows=rows,
        dimensions=summaries,
        latency_mean_ms=sum(latencies) / len(latencies) if latencies else None,
        latency_rows_missing=len(rows) - len(latencies),
        errors=sum(1 for row in rows if row.error is not None),
        claims=RunClaims(),
    )


def run_judge(
    judge: Judge,
    judge_name: str,
    snapshots: Sequence[ReplaySnapshot],
    report: EvaluationReport,
    *,
    max_rows: int,
) -> JudgedSummary:
    """Rate replies with a caller-supplied judge, for at most ``max_rows`` rows.

    The judge is always passed in explicitly (nothing here constructs a provider client),
    its ratings are labeled ``model_judged`` and they are returned apart from the
    deterministic scores. Rows beyond the cap are not rated, not silently scored.
    """
    by_key = {(s.case_id, s.turn_id): s for s in snapshots}
    judged: list[JudgedRow] = []
    for row in report.rows[:max_rows]:
        snapshot = by_key[(row.case_id, row.turn_id)]
        if row.response is None:
            judged.append(
                JudgedRow(case_id=row.case_id, turn_id=row.turn_id, rating=None, error="no reply")
            )
            continue
        try:
            rating = judge(snapshot, row.response)
            judged.append(
                JudgedRow(case_id=row.case_id, turn_id=row.turn_id, rating=rating, error=None)
            )
        except Exception as caught:
            judged.append(
                JudgedRow(
                    case_id=row.case_id,
                    turn_id=row.turn_id,
                    rating=None,
                    error=_sanitized(caught),
                )
            )
    ratings = [row.rating.rating for row in judged if row.rating is not None]
    return JudgedSummary(
        judge_name=judge_name,
        rows=judged,
        mean_rating=sum(ratings) / len(ratings) if ratings else None,
        errors=sum(1 for row in judged if row.error is not None),
    )
