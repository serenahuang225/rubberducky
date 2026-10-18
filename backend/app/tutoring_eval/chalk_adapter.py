"""Explicit Chalk Compute adapter: upload a pinned replay dataset, evaluate, read results back.

What this adapter does and does not establish
- Nothing here runs at import, at app startup or on a health check. The SDK is imported only
  inside ``ChalkEvaluationAdapter.run``, and the deploying function modules only inside
  ``load_remote_functions`` after every activation check passed.
- Activation needs ``EXTERNAL_INTEGRATIONS_ENABLED``, ``CHALK_EVALUATIONS_ENABLED`` and a
  complete explicit credential set (id, secret, environment). Credentials alone never
  activate it, an ambient ``chalk login`` is never used, and the strongest status this build
  reports is ``configured_unverified``: no live Chalk call has been made.
- A cloud run that reports ``succeeded`` is not accepted as success. Per-row task errors,
  per-scorer errors, missing result columns, a short result table and scores that differ from
  the local rubric are all reported, and ``usable`` is false when any is present.
- Remote latency is not measured by this adapter. Latency in the result is the local
  candidate-call latency carried in the dataset, or missing.
"""

import contextlib
import importlib
import json
import math
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.redaction import redact_text
from app.schemas.interactives import IntegrationState
from app.tutoring_eval.cases import CASE_SET_VERSION
from app.tutoring_eval.contracts import (
    DIMENSIONS,
    EvaluationReport,
    ReplaySnapshot,
    RowResult,
)
from app.tutoring_eval.replay import rubric_context
from app.tutoring_eval.rubric import RUBRIC_VERSION

CHALK_DATASET_NAME = "rubberducky-tutoring-replay"
CHALK_SUITE_NAME = "rubberducky-tutoring"
CHALK_HOST_SUFFIX = "chalk.ai"
FUNCTIONS_MODULE = "app.tutoring_eval.chalk_functions"
JUDGE_MODULE = "app.tutoring_eval.chalk_judge"
JUDGE_MODEL_ENV = "TUTORING_EVAL_JUDGE_MODEL"
JUDGE_SCORER_NAME = "tutoring-judge"
TASK_FUNCTION_NAME = "tutoring_replay_candidate"
SCORER_FUNCTION_NAMES: dict[str, str] = {name: f"tutoring_score_{name}" for name in DIMENSIONS}
# Tolerance when comparing a remote score with the identical local computation.
PARITY_TOLERANCE = 1e-9
POLL_INTERVAL_SECONDS = 2.0


class ChalkNotActivatedError(RuntimeError):
    """The explicit activation conditions are not all met; nothing was contacted."""


# --- status ---------------------------------------------------------------------------------


class ChalkEvaluationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["chalk-evaluation-status.v1"] = "chalk-evaluation-status.v1"
    name: Literal["chalk_evaluations"] = "chalk_evaluations"
    state: IntegrationState
    label: str
    detail: str
    missing: tuple[str, ...] = ()
    judge_requested_in_config: bool = False
    # No live Chalk call has been made by this build.
    verified_at: None = None


def validate_chalk_api_server(url: str) -> str:
    """Return the host of a Chalk API server URL, or raise ``ValueError`` without echoing it."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password:
        raise ValueError("CHALK_API_SERVER must be https without embedded credentials")
    if parts.port not in (None, 443):
        raise ValueError("CHALK_API_SERVER must use the standard https port")
    if host != CHALK_HOST_SUFFIX and not host.endswith(f".{CHALK_HOST_SUFFIX}"):
        raise ValueError("CHALK_API_SERVER host must belong to chalk.ai")
    return host


def _secret(value: Any) -> str:
    return "" if value is None else str(value.get_secret_value())


def describe_chalk_evaluation(settings: Settings) -> ChalkEvaluationStatus:
    """Derive status from configuration alone: no SDK import, no network."""
    judge = settings.chalk_judge_enabled
    if not (settings.external_integrations_enabled and settings.chalk_evaluations_enabled):
        return ChalkEvaluationStatus(
            state="disabled",
            label="Chalk tutoring evaluation (disabled)",
            detail=(
                "Needs EXTERNAL_INTEGRATIONS_ENABLED=true and CHALK_EVALUATIONS_ENABLED=true. "
                "Nothing is uploaded, deployed or run."
            ),
            judge_requested_in_config=judge,
        )
    missing = [
        name
        for name, present in (
            ("CHALK_CLIENT_ID", bool(_secret(settings.chalk_client_id))),
            ("CHALK_CLIENT_SECRET", bool(_secret(settings.chalk_client_secret))),
            ("CHALK_ENVIRONMENT", bool(settings.chalk_environment)),
        )
        if not present
    ]
    if settings.chalk_api_server:
        try:
            validate_chalk_api_server(settings.chalk_api_server)
        except ValueError:
            missing.append("CHALK_API_SERVER (must be an https chalk.ai host)")
    if judge and not settings.chalk_judge_model:
        missing.append("CHALK_JUDGE_MODEL")
    if missing:
        return ChalkEvaluationStatus(
            state="not_configured",
            label="Chalk tutoring evaluation (not configured)",
            detail="Missing configuration: " + ", ".join(missing) + ".",
            missing=tuple(missing),
            judge_requested_in_config=judge,
        )
    return ChalkEvaluationStatus(
        state="configured_unverified",
        label="Chalk tutoring evaluation (configured, unverified)",
        detail=(
            "No live Chalk call has been made, so credentials, Evaluations and async Function "
            "queue enablement, an active deployment, usage cost and result handling are "
            "unverified. A run uploads a small fictional dataset and deploys functions only "
            "when explicitly started with --confirm-live."
        ),
        judge_requested_in_config=judge,
    )


# --- dataset rows ---------------------------------------------------------------------------


class DatasetPlan(BaseModel):
    """The pinned shape that would be uploaded; computed locally, nothing sent."""

    schema_version: Literal["chalk-dataset-plan.v1"] = "chalk-dataset-plan.v1"
    dataset_name: str = CHALK_DATASET_NAME
    case_set_version: str = CASE_SET_VERSION
    rubric_version: str = RUBRIC_VERSION
    columns: list[str]
    row_count: int
    row_ids: list[str]
    snapshot_digests: dict[str, str]
    # Rows left out because the candidate produced no reply; each is listed, none dropped silently.
    excluded_rows: dict[str, str]
    task_function: str = TASK_FUNCTION_NAME
    scorer_functions: dict[str, str] = Field(default_factory=lambda: dict(SCORER_FUNCTION_NAMES))


DATASET_COLUMNS: tuple[str, ...] = (
    "row_id",
    "case_id",
    "turn_id",
    "scenario",
    "snapshot_digest",
    "cutoff_utc",
    "learner_message",
    "history_json",
    "history_source_ids_json",
    "omitted_future_events",
    "rubric_context_json",
    "candidate_name",
    "candidate_label",
    "candidate_text",
    "cited_source_ids_json",
    "answer_revealed_claim",
    "local_latency_ms",
    "local_latency_source",
)


def row_id(case_id: str, turn_id: str) -> str:
    return f"{case_id}::{turn_id}"


def _claim(value: bool | None) -> str:
    return "unstated" if value is None else ("true" if value else "false")


def _compact(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_dataset_rows(
    snapshots: Sequence[ReplaySnapshot], report: EvaluationReport
) -> tuple[list[dict[str, object]], DatasetPlan]:
    """One dataset row per replayed turn that has a candidate reply.

    Each row carries only the bounded history the replay allowed (with source IDs), never
    later events, and the local latency exactly as measured or supplied (``None`` if neither).
    """
    by_key: dict[tuple[str, str], RowResult] = {(r.case_id, r.turn_id): r for r in report.rows}
    rows: list[dict[str, object]] = []
    excluded: dict[str, str] = {}
    for snapshot in snapshots:
        result = by_key.get((snapshot.case_id, snapshot.turn_id))
        rid = row_id(snapshot.case_id, snapshot.turn_id)
        if result is None or result.response is None:
            excluded[rid] = (result.error if result and result.error else "no reply") or "no reply"
            continue
        rows.append(
            {
                "row_id": rid,
                "case_id": snapshot.case_id,
                "turn_id": snapshot.turn_id,
                "scenario": snapshot.scenario,
                "snapshot_digest": snapshot.digest,
                "cutoff_utc": snapshot.cutoff.isoformat(),
                "learner_message": snapshot.learner_message,
                "history_json": _compact([e.model_dump(mode="json") for e in snapshot.history]),
                "history_source_ids_json": _compact(snapshot.available_source_ids),
                "omitted_future_events": snapshot.omitted_future_events,
                "rubric_context_json": _compact(rubric_context(snapshot)),
                "candidate_name": report.candidate_name,
                "candidate_label": report.candidate_label,
                "candidate_text": result.response.text,
                "cited_source_ids_json": _compact(result.response.cited_source_ids),
                "answer_revealed_claim": _claim(result.response.answer_revealed),
                "local_latency_ms": result.latency_ms,
                "local_latency_source": result.latency_source,
            }
        )
    plan = DatasetPlan(
        columns=list(DATASET_COLUMNS),
        row_count=len(rows),
        row_ids=[str(r["row_id"]) for r in rows],
        snapshot_digests={str(r["row_id"]): str(r["snapshot_digest"]) for r in rows},
        excluded_rows={k: redact_text(v) for k, v in excluded.items()},
    )
    return rows, plan


def rows_to_table(rows: Sequence[Mapping[str, object]]) -> Any:
    """An Arrow table with an explicit schema, so an all-missing latency column stays float."""
    import pyarrow as pa  # type: ignore[import-untyped]

    typed = {
        "omitted_future_events": pa.field("omitted_future_events", pa.int64(), nullable=False),
        "local_latency_ms": pa.field("local_latency_ms", pa.float64(), nullable=True),
    }
    schema = pa.schema(
        [typed.get(c) or pa.field(c, pa.string(), nullable=False) for c in DATASET_COLUMNS]
    )
    return pa.Table.from_pylist([dict(row) for row in rows], schema=schema)


# --- results --------------------------------------------------------------------------------


class ScorerOutcome(BaseModel):
    dimension: str
    scorer: str
    rows_scored: int
    rows_not_applicable: int
    rows_errored: int
    mean: float | None


class RowOutcome(BaseModel):
    row_id: str
    output_error: str | None
    scorer_errors: dict[str, str]
    scores: dict[str, float | None]
    latency_ms: float | None
    latency_source: str


class ChalkRunReport(BaseModel):
    schema_version: Literal["chalk-evaluation-result.v1"] = "chalk-evaluation-result.v1"
    kind: Literal["deterministic_remote"] = "deterministic_remote"
    # "injected_fixture": a test or fixture transport answered. Only "live_chalk" touched Chalk.
    transport: Literal["injected_fixture", "live_chalk"]
    run_status: str
    run_error: str | None
    cloud_status_is_sufficient: Literal[False] = False
    # True only when the run succeeded AND no row, scorer or column problem was found.
    usable: bool
    problems: list[str]
    expected_rows: int
    result_rows: int
    rows_with_task_error: int
    rows_with_scorer_error: int
    scorers: list[ScorerOutcome]
    rows: list[RowOutcome]
    parity_mismatches: list[str]
    remote_latency_ms: None = None
    remote_latency_note: str = (
        "Remote latency is not measured; latency_ms is the local candidate call, or missing."
    )
    dataset_revision: dict[str, str]
    result_dataset: dict[str, str] | None
    judged: dict[str, Any] | None = None
    claims: dict[str, bool] = Field(
        default_factory=lambda: {"trained_model_result": False, "learning_gain_claim": False}
    )


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _finite_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def normalize_result_table(
    table: Any,
    *,
    run_status: str,
    run_error: str | None,
    plan: DatasetPlan,
    local_report: EvaluationReport,
    transport: Literal["injected_fixture", "live_chalk"],
    dataset_revision: Mapping[str, str],
    result_dataset: Mapping[str, str] | None,
    include_judge: bool = False,
) -> ChalkRunReport:
    """Turn a result table into per-row outcomes and a list of problems.

    The result table holds the dataset's columns plus ``output``, ``output_error`` and, per
    scorer, ``<name>_value``, ``<name>_error`` and ``<name>_metadata``. A succeeded run may
    still contain errors in any of them, so every one is read.
    """
    problems: list[str] = []
    columns = set(getattr(table, "column_names", []))
    records: list[dict[str, Any]] = table.to_pylist() if table is not None else []
    local_by_row = {row_id(r.case_id, r.turn_id): r for r in local_report.rows}

    if run_status != "succeeded":
        problems.append(f"run status is {run_status}")
    if len(records) != plan.row_count:
        problems.append(f"expected {plan.row_count} result rows, found {len(records)}")
    for required in ("row_id", "output", "output_error"):
        if required not in columns:
            problems.append(f"result is missing column {required}")
    expected_scorers = dict(SCORER_FUNCTION_NAMES)
    for scorer in expected_scorers.values():
        for suffix in ("_value", "_error"):
            if f"{scorer}{suffix}" not in columns:
                problems.append(f"result is missing column {scorer}{suffix}")
    if include_judge and f"{JUDGE_SCORER_NAME}_value" not in columns:
        problems.append(f"result is missing column {JUDGE_SCORER_NAME}_value")

    outcomes: list[RowOutcome] = []
    parity: list[str] = []
    counts = {dim: {"scored": 0, "na": 0, "err": 0, "sum": 0.0} for dim in expected_scorers}
    task_errors = 0
    scorer_error_rows = 0
    for record in records:
        rid = str(record.get("row_id", ""))
        output_error = _text_or_none(record.get("output_error"))
        if output_error or _text_or_none(record.get("output")) is None:
            task_errors += 1
            output_error = output_error or "task produced no output"
        scorer_errors: dict[str, str] = {}
        scores: dict[str, float | None] = {}
        local_row = local_by_row.get(rid)
        local_scores: dict[str, float | None] = {}
        if local_row is not None:
            local_scores = {s.dimension: s.value for s in local_row.scores}
        for dimension, scorer in expected_scorers.items():
            error = _text_or_none(record.get(f"{scorer}_error"))
            raw = record.get(f"{scorer}_value")
            value = _finite_score(raw)
            if error is None and raw is not None and value is None:
                error = "score is not a finite number in [0, 1]"
            if error:
                scorer_errors[dimension] = redact_text(error)[:200]
                counts[dimension]["err"] += 1
                scores[dimension] = None
                continue
            scores[dimension] = value
            if value is None:
                counts[dimension]["na"] += 1
            else:
                counts[dimension]["scored"] += 1
                counts[dimension]["sum"] += value
            expected_local = local_scores.get(dimension)
            if (value is None) != (expected_local is None) or (
                value is not None
                and expected_local is not None
                and abs(value - expected_local) > PARITY_TOLERANCE
            ):
                parity.append(f"{rid}:{dimension} remote={value} local={expected_local}")
        if scorer_errors:
            scorer_error_rows += 1
        outcomes.append(
            RowOutcome(
                row_id=rid,
                output_error=redact_text(output_error)[:200] if output_error else None,
                scorer_errors=scorer_errors,
                scores=scores,
                latency_ms=local_row.latency_ms if local_row else None,
                latency_source=local_row.latency_source if local_row else "missing",
            )
        )
    if task_errors:
        problems.append(f"{task_errors} row(s) have a task error or no output")
    if scorer_error_rows:
        problems.append(f"{scorer_error_rows} row(s) have a scorer error")
    if parity:
        problems.append(f"{len(parity)} remote score(s) differ from the local rubric")
    missing_ids = sorted(set(plan.row_ids) - {o.row_id for o in outcomes})
    if missing_ids:
        problems.append("rows absent from the result: " + ", ".join(missing_ids))

    scorers = [
        ScorerOutcome(
            dimension=dimension,
            scorer=scorer,
            rows_scored=int(counts[dimension]["scored"]),
            rows_not_applicable=int(counts[dimension]["na"]),
            rows_errored=int(counts[dimension]["err"]),
            mean=(
                counts[dimension]["sum"] / counts[dimension]["scored"]
                if counts[dimension]["scored"]
                else None
            ),
        )
        for dimension, scorer in expected_scorers.items()
    ]
    return ChalkRunReport(
        transport=transport,
        run_status=run_status,
        run_error=redact_text(run_error)[:200] if run_error else None,
        usable=not problems,
        problems=problems,
        expected_rows=plan.row_count,
        result_rows=len(records),
        rows_with_task_error=task_errors,
        rows_with_scorer_error=scorer_error_rows,
        scorers=scorers,
        rows=outcomes,
        parity_mismatches=parity,
        dataset_revision=dict(dataset_revision),
        result_dataset=dict(result_dataset) if result_dataset else None,
        judged=_judged_from_records(records) if include_judge else None,
    )


def _judged_from_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Judge ratings stay in their own block, labeled model_judged, never merged with scores."""
    ratings: list[float] = []
    errors = 0
    for record in records:
        if _text_or_none(record.get(f"{JUDGE_SCORER_NAME}_error")):
            errors += 1
            continue
        value = _finite_score(record.get(f"{JUDGE_SCORER_NAME}_value"))
        if value is not None:
            ratings.append(value)
    return {
        "kind": "model_judged",
        "scorer": JUDGE_SCORER_NAME,
        "rated_rows": len(ratings),
        "errored_rows": errors,
        "mean_rating": sum(ratings) / len(ratings) if ratings else None,
    }


# --- adapter --------------------------------------------------------------------------------


@dataclass
class RemoteFunctions:
    task: Any
    scorers: dict[str, Any]
    judge: Any | None = None


def load_remote_functions(include_judge: bool, judge_model: str | None = None) -> RemoteFunctions:
    """Import the function modules, which deploys them. Called only after activation checks."""
    module = importlib.import_module(FUNCTIONS_MODULE)
    judge = None
    if include_judge:
        if not judge_model:
            raise ChalkNotActivatedError("a judge was requested without CHALK_JUDGE_MODEL")
        os.environ[JUDGE_MODEL_ENV] = judge_model
        judge = importlib.import_module(JUDGE_MODULE).tutoring_judge
    return RemoteFunctions(
        task=getattr(module, TASK_FUNCTION_NAME),
        scorers={dim: getattr(module, name) for dim, name in SCORER_FUNCTION_NAMES.items()},
        judge=judge,
    )


@dataclass
class ChalkSeams:
    """Injection points for tests and fixtures. All default to the real SDK paths."""

    connect_client: Any | None = None
    http_client: Any | None = None
    function_loader: Callable[[bool, str | None], RemoteFunctions] = load_remote_functions
    sleep: Callable[[float], None] = time.sleep


@contextlib.contextmanager
def _sdk_credentials(settings: Settings) -> Iterator[None]:
    """Expose the explicit credentials to the SDK, which reads process environment only.

    The SDK would otherwise fall back to a ``chalk login`` token file; having all three set
    makes it use these instead. Values are restored afterwards.
    """
    wanted = {
        "CHALK_CLIENT_ID": _secret(settings.chalk_client_id),
        "CHALK_CLIENT_SECRET": _secret(settings.chalk_client_secret),
        "CHALK_ENVIRONMENT": settings.chalk_environment or "",
        "CHALK_API_SERVER": settings.chalk_api_server or "",
    }
    previous = {key: os.environ.get(key) for key in wanted}
    try:
        for key, value in wanted.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        yield
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


@dataclass
class RecordedRequest:
    """A normalized description of one adapter step, kept for the report and for tests."""

    step: str
    detail: dict[str, Any] = field(default_factory=dict)


class ChalkEvaluationAdapter:
    def __init__(self, settings: Settings, seams: ChalkSeams | None = None) -> None:
        self._settings = settings
        self._seams = seams or ChalkSeams()
        self.requests: list[RecordedRequest] = []

    def status(self) -> ChalkEvaluationStatus:
        return describe_chalk_evaluation(self._settings)

    def _require_activation(self, row_count: int, include_judge: bool) -> None:
        status = self.status()
        if status.state != "configured_unverified":
            raise ChalkNotActivatedError(f"Chalk evaluation is {status.state}: {status.detail}")
        if row_count == 0:
            raise ChalkNotActivatedError("there are no rows with a candidate reply to evaluate")
        if row_count > self._settings.chalk_max_rows:
            raise ChalkNotActivatedError(
                f"{row_count} rows exceed CHALK_MAX_ROWS={self._settings.chalk_max_rows}; "
                "nothing is truncated or uploaded"
            )
        if include_judge and not (
            self._settings.chalk_judge_enabled and self._settings.chalk_judge_model
        ):
            raise ChalkNotActivatedError(
                "a model judge needs CHALK_JUDGE_ENABLED=true and CHALK_JUDGE_MODEL"
            )

    def run(
        self,
        snapshots: Sequence[ReplaySnapshot],
        report: EvaluationReport,
        *,
        evaluation_name: str,
        include_judge: bool = False,
    ) -> ChalkRunReport:
        rows, plan = build_dataset_rows(snapshots, report)
        self._require_activation(len(rows), include_judge)
        injected = self._seams.connect_client is not None
        with _sdk_credentials(self._settings) if not injected else contextlib.nullcontext():
            return self._run_with_sdk(rows, plan, report, evaluation_name, include_judge, injected)

    def _run_with_sdk(
        self,
        rows: list[dict[str, object]],
        plan: DatasetPlan,
        report: EvaluationReport,
        evaluation_name: str,
        include_judge: bool,
        injected: bool,
    ) -> ChalkRunReport:
        import chalkcompute

        connect = self._seams.connect_client
        datasets = chalkcompute.DatasetClient(
            connect_client=connect, http_client=self._seams.http_client
        )
        client = chalkcompute.EvaluationClient(connect_client=connect)

        table = rows_to_table(rows)
        self.requests.append(
            RecordedRequest(
                "dataset_upload",
                {"name": CHALK_DATASET_NAME, "rows": table.num_rows, "columns": table.column_names},
            )
        )
        revision = datasets.upload(CHALK_DATASET_NAME, table)

        functions = self._seams.function_loader(include_judge, self._settings.chalk_judge_model)
        scorers = [functions.scorers[dim] for dim in DIMENSIONS]
        if include_judge and functions.judge is not None:
            scorers.append(functions.judge)
        metadata = {
            "rubric_version": RUBRIC_VERSION,
            "case_set_version": CASE_SET_VERSION,
            "candidate_name": report.candidate_name,
            "candidate_label": report.candidate_label,
            "judge_included": include_judge,
            "note": "authored fictional cases; deterministic rubric; not a trained-model result",
        }
        suite = next((s for s in client.list_suites() if s.name == CHALK_SUITE_NAME), None)
        suite = suite or client.create_suite(CHALK_SUITE_NAME)
        evaluation = client.create(
            evaluation_name,
            dataset=revision,
            task=functions.task,
            scorers=scorers,
            metadata=metadata,
            suite_id=suite.id,
        )
        self.requests.append(
            RecordedRequest(
                "evaluation_create",
                {
                    "name": evaluation_name,
                    "dataset": {"id": revision.dataset_id, "revision": revision.revision_id},
                    "scorer_count": len(scorers),
                    "suite": CHALK_SUITE_NAME,
                },
            )
        )
        run = client.run(evaluation.id, metadata={"candidate_label": report.candidate_label})
        run = self._wait(run)
        table_out = None
        if run.result_dataset is not None and run.status.value == "succeeded":
            table_out = datasets.read(run.result_dataset)
        result = normalize_result_table(
            table_out,
            run_status=run.status.value,
            run_error=run.error_message,
            plan=plan,
            local_report=report,
            transport="injected_fixture" if injected else "live_chalk",
            dataset_revision={
                "dataset_id": str(revision.dataset_id),
                "revision_id": str(revision.revision_id),
            },
            result_dataset=(
                {
                    "dataset_id": str(run.result_dataset.dataset_id),
                    "revision_id": str(run.result_dataset.revision_id),
                }
                if run.result_dataset
                else None
            ),
            include_judge=include_judge,
        )
        return result

    def _wait(self, run: Any) -> Any:
        deadline = time.monotonic() + self._settings.chalk_run_timeout_seconds
        current = run
        while not current.is_terminal:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Chalk run {run.id} did not finish within "
                    f"{self._settings.chalk_run_timeout_seconds:g}s; it may still be running"
                )
            self._seams.sleep(POLL_INTERVAL_SECONDS)
            current = current.refresh()
        return current
