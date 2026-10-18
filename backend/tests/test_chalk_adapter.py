"""The Chalk Compute evaluation adapter against the installed SDK on fixture transports.

``DatasetClient`` and ``EvaluationClient`` run for real; only the ConnectRPC client and the
signed-URL HTTP client under them are replaced (see ``chalk_fixtures``). Every run here is
labeled ``injected_fixture``: nothing in this module contacts Chalk, so none of it verifies a
live account, queue enablement, cost, latency or the real scorer deployment.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from chalkcompute import DatasetError, EvaluationError
from connectrpc.code import Code

from app.config import Settings
from app.tutoring_eval import cli as eval_cli
from app.tutoring_eval.candidates import fixture_candidate, responses_file_candidate
from app.tutoring_eval.cases import build_fixture_cases
from app.tutoring_eval.chalk_adapter import (
    CHALK_DATASET_NAME,
    CHALK_SUITE_NAME,
    DATASET_COLUMNS,
    JUDGE_SCORER_NAME,
    SCORER_FUNCTION_NAMES,
    ChalkEvaluationAdapter,
    ChalkNotActivatedError,
    _sdk_credentials,
    build_dataset_rows,
    describe_chalk_evaluation,
    load_remote_functions,
    rows_to_table,
    validate_chalk_api_server,
)
from app.tutoring_eval.contracts import DIMENSIONS, EvaluationReport, ReplaySnapshot
from app.tutoring_eval.replay import build_snapshots, rubric_context
from app.tutoring_eval.runner import evaluate_candidate
from tests.chalk_fixtures import (
    DATASET_ID,
    EVALUATION_ID,
    FIXTURE_CLIENT_ID,
    FIXTURE_CLIENT_SECRET,
    REVISION_ID,
    SUITE_ID,
    UPLOAD_URL,
    ChalkWorld,
    Columns,
    chalk_settings,
    rpc_error,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
JUDGE_MODEL = "example/judge-model"


def replay(name: str = "good") -> tuple[list[ReplaySnapshot], EvaluationReport]:
    snapshots = build_snapshots(build_fixture_cases())
    return snapshots, evaluate_candidate(fixture_candidate(name), snapshots)


def run_adapter(
    cloud: ChalkWorld,
    settings: Settings | None = None,
    *,
    candidate: str = "good",
    include_judge: bool = False,
) -> Any:
    snapshots, report = replay(candidate)
    adapter = ChalkEvaluationAdapter(settings or chalk_settings(), cloud.seams())
    return adapter.run(
        snapshots, report, evaluation_name="fixture-eval", include_judge=include_judge
    )


def judge_settings(**overrides: object) -> Settings:
    return chalk_settings(chalk_judge_enabled=True, chalk_judge_model=JUDGE_MODEL, **overrides)


@pytest.fixture(autouse=True)
def _no_ambient_chalk_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CHALK_CLIENT_ID", "CHALK_CLIENT_SECRET", "CHALK_ENVIRONMENT", "CHALK_API_SERVER"):
        monkeypatch.delenv(key, raising=False)


# --- status -----------------------------------------------------------------------------


def test_disabled_by_default() -> None:
    status = describe_chalk_evaluation(Settings.model_validate({"database_url": "sqlite://"}))
    assert status.state == "disabled"
    assert status.verified_at is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"chalk_evaluations_enabled": False},
        {"external_integrations_enabled": False},
    ],
)
def test_both_switches_are_needed_even_with_credentials(overrides: dict[str, object]) -> None:
    assert describe_chalk_evaluation(chalk_settings(**overrides)).state == "disabled"


@pytest.mark.parametrize(
    ("missing", "label"),
    [
        ("chalk_client_id", "CHALK_CLIENT_ID"),
        ("chalk_client_secret", "CHALK_CLIENT_SECRET"),
        ("chalk_environment", "CHALK_ENVIRONMENT"),
    ],
)
def test_each_missing_credential_is_named_and_none_is_inferred(missing: str, label: str) -> None:
    status = describe_chalk_evaluation(chalk_settings(**{missing: None}))
    assert status.state == "not_configured"
    assert status.missing == (label,)


def test_complete_configuration_is_unverified_and_never_exposes_the_secret() -> None:
    status = describe_chalk_evaluation(chalk_settings())
    assert status.state == "configured_unverified"
    assert status.verified_at is None
    dumped = status.model_dump_json()
    assert FIXTURE_CLIENT_SECRET not in dumped and FIXTURE_CLIENT_ID not in dumped


def test_a_judge_model_is_never_defaulted() -> None:
    status = describe_chalk_evaluation(chalk_settings(chalk_judge_enabled=True))
    assert status.state == "not_configured"
    assert status.missing == ("CHALK_JUDGE_MODEL",)
    assert status.judge_requested_in_config is True


@pytest.mark.parametrize(
    "url",
    [
        "http://api.chalk.ai",
        "https://api.chalk.ai.evil.example",
        "https://evil.example/chalk.ai",
        "https://user:pass@api.chalk.ai",
        "https://api.chalk.ai:8443",
        "https://notchalk.ai",
        "",
    ],
)
def test_api_server_must_be_an_https_chalk_host(url: str) -> None:
    with pytest.raises(ValueError, match="CHALK_API_SERVER"):
        validate_chalk_api_server(url)
    status = describe_chalk_evaluation(chalk_settings(chalk_api_server=url or "x"))
    assert status.state == "not_configured"


@pytest.mark.parametrize("url", ["https://api.chalk.ai", "https://api.staging.chalk.ai/"])
def test_chalk_hosts_are_accepted(url: str) -> None:
    assert validate_chalk_api_server(url).endswith("chalk.ai")
    assert describe_chalk_evaluation(chalk_settings(chalk_api_server=url)).state == (
        "configured_unverified"
    )


# --- dataset rows -----------------------------------------------------------------------


def test_dataset_rows_carry_bounded_history_with_source_ids_and_no_future_events() -> None:
    snapshots, report = replay()
    rows, plan = build_dataset_rows(snapshots, report)
    assert plan.row_count == len(rows) == len(snapshots)
    assert plan.excluded_rows == {}
    assert plan.columns == list(DATASET_COLUMNS)
    assert plan.case_set_version.startswith("tutoring-fixture-cases")
    by_id = {str(r["row_id"]): r for r in rows}
    for snapshot in snapshots:
        row = by_id[f"{snapshot.case_id}::{snapshot.turn_id}"]
        assert json.loads(str(row["history_source_ids_json"])) == snapshot.available_source_ids
        assert [e["source_id"] for e in json.loads(str(row["history_json"]))] == (
            snapshot.available_source_ids
        )
        assert "future." not in str(row["history_json"]) + str(row["rubric_context_json"])
        assert (
            row["snapshot_digest"] == snapshot.digest == plan.snapshot_digests[str(row["row_id"])]
        )
        assert json.loads(str(row["rubric_context_json"])) == rubric_context(snapshot)
    assert any(int(str(r["omitted_future_events"])) > 0 for r in rows)


def test_dataset_rows_have_no_reserved_chalk_column_names() -> None:
    reserved = {"output", "trace", "__chalk_evaluation_output", "__chalk_evaluation_row_id"}
    assert reserved.isdisjoint(DATASET_COLUMNS)
    assert not [c for c in DATASET_COLUMNS if c.startswith("__chalk")]


def test_fixture_latency_stays_missing_in_the_dataset_and_is_a_float_column() -> None:
    snapshots, report = replay()
    rows, _ = build_dataset_rows(snapshots, report)
    assert all(row["local_latency_ms"] is None for row in rows)
    assert all(row["local_latency_source"] == "missing" for row in rows)
    assert {row["candidate_label"] for row in rows} == {"fixture"}
    table = rows_to_table(rows)
    assert table.schema.field("local_latency_ms").type == pa.float64()
    assert table.schema.field("omitted_future_events").type == pa.int64()
    assert table.num_rows == len(rows)


def test_rows_without_a_candidate_reply_are_listed_not_dropped_silently(tmp_path: Path) -> None:
    snapshots = build_snapshots(build_fixture_cases())
    first = snapshots[0]
    path = tmp_path / "partial.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": first.case_id,
                "turn_id": first.turn_id,
                "text": "What does the 2 multiply?",
                "latency_ms": 12.5,
            }
        )
    )
    report = evaluate_candidate(responses_file_candidate(path), snapshots)
    rows, plan = build_dataset_rows(snapshots, report)
    assert len(rows) == 1 and plan.row_count == 1
    assert len(plan.excluded_rows) == len(snapshots) - 1
    assert rows[0]["local_latency_ms"] == 12.5
    assert rows[0]["local_latency_source"] == "supplied_by_candidate_source"
    assert rows[0]["candidate_label"] == "external_responses"


# --- remote functions: nothing deploys until asked --------------------------------------


def test_function_modules_deploy_only_when_loaded_explicitly(world: ChalkWorld) -> None:
    assert world.deployments == []
    loaded = load_remote_functions(include_judge=False)
    assert sorted(world.deployments) == sorted(
        ["tutoring_replay_candidate", *SCORER_FUNCTION_NAMES.values()]
    )
    assert loaded.judge is None
    assert set(loaded.scorers) == set(DIMENSIONS)


def test_a_judge_without_a_model_is_refused_before_its_module_is_imported(
    world: ChalkWorld,
) -> None:
    with pytest.raises(ChalkNotActivatedError, match="CHALK_JUDGE_MODEL"):
        load_remote_functions(include_judge=True, judge_model=None)
    assert "app.tutoring_eval.chalk_judge" not in sys.modules
    assert not [name for name in world.deployments if "judge" in name]


def test_remote_scorers_reproduce_the_local_rubric_and_emit_nothing_when_not_applicable(
    world: ChalkWorld,
) -> None:
    functions = load_remote_functions(include_judge=False)
    snapshots, report = replay()
    for snapshot, row in zip(snapshots, report.rows, strict=True):
        assert row.response is not None
        context = json.dumps(rubric_context(snapshot), sort_keys=True)
        cited = json.dumps(row.response.cited_source_ids)
        claim = {True: "true", False: "false", None: "unstated"}[row.response.answer_revealed]
        local = {s.dimension: s.value for s in row.scores}
        for dimension in DIMENSIONS:
            results = functions.scorers[dimension](row.response.text, context, cited, claim)
            if local[dimension] is None:
                assert results == []
            else:
                assert len(results) == 1
                assert results[0].score == pytest.approx(local[dimension])
                assert results[0].metadata["kind"] == "deterministic"


# --- activation gates -------------------------------------------------------------------


def test_a_disabled_adapter_contacts_nothing_and_loads_nothing(world: ChalkWorld) -> None:
    with pytest.raises(ChalkNotActivatedError, match="disabled"):
        run_adapter(world, Settings.model_validate({"database_url": "sqlite://"}))
    assert world.rpcs == [] and world.http.requests == []
    assert world.function_loads == [] and world.deployments == []


def test_missing_credentials_refuse_before_any_request(world: ChalkWorld) -> None:
    with pytest.raises(ChalkNotActivatedError, match="not_configured"):
        run_adapter(world, chalk_settings(chalk_client_secret=None))
    assert world.rpcs == [] and world.deployments == []


def test_row_cap_refuses_without_truncating_or_uploading(world: ChalkWorld) -> None:
    with pytest.raises(ChalkNotActivatedError, match="CHALK_MAX_ROWS"):
        run_adapter(world, chalk_settings(chalk_max_rows=3))
    assert world.rpcs == [] and world.deployments == [] and world.http.uploads == {}


def test_no_rows_to_evaluate_is_refused(world: ChalkWorld, tmp_path: Path) -> None:
    snapshots = build_snapshots(build_fixture_cases())
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    report = evaluate_candidate(responses_file_candidate(empty), snapshots)
    adapter = ChalkEvaluationAdapter(chalk_settings(), world.seams())
    with pytest.raises(ChalkNotActivatedError, match="no rows"):
        adapter.run(snapshots, report, evaluation_name="x")
    assert world.rpcs == []


def test_a_judge_needs_its_own_enablement_and_model(world: ChalkWorld) -> None:
    with pytest.raises(ChalkNotActivatedError, match="CHALK_JUDGE_ENABLED"):
        run_adapter(world, chalk_settings(), include_judge=True)
    assert world.rpcs == [] and world.function_loads == []


# --- a faithful run: normalized requests and results ------------------------------------


def test_upload_evaluation_and_run_requests_are_normalized_and_pinned(
    world: ChalkWorld,
    no_network: list[tuple[str, object]],
) -> None:
    result = run_adapter(world)

    assert world.names() == [
        "get_dataset_upload_uris",
        "finalize_dataset_upload",
        "list_evaluation_suites",
        "create_evaluation_suite",
        "create_evaluation",
        "create_evaluation_run",
        "get_evaluation_run",
        "get_evaluation_run",
        "get_dataset_revision_download_links",
    ]
    assert no_network == []
    assert world.http.requests[0] == ("PUT", UPLOAD_URL)

    finalize = world.requests_named("finalize_dataset_upload")[0]
    assert finalize.dataset_name == CHALK_DATASET_NAME
    uploaded = pq.read_table(io.BytesIO(world.http.uploads[UPLOAD_URL]))
    assert uploaded.column_names == list(DATASET_COLUMNS)
    assert uploaded.num_rows == len(build_snapshots(build_fixture_cases()))
    assert pa.ipc.read_schema(pa.py_buffer(finalize.arrow_schema_serialized)).names == list(
        DATASET_COLUMNS
    )
    assert "future." not in "".join(uploaded["history_json"].to_pylist())

    created = world.created_evaluation
    assert created.name == "fixture-eval"
    assert (created.dataset_id, created.dataset_revision_id) == (DATASET_ID, REVISION_ID)
    assert created.dataset_name == ""
    assert created.suite_id == SUITE_ID
    assert created.task_function_version_id == "function-version-tutoring_replay_candidate"
    pinned = [s.implementation.value.function_version_id for s in created.scorers]
    assert pinned == [f"function-version-{SCORER_FUNCTION_NAMES[d]}" for d in DIMENSIONS]
    assert all(s.implementation.field == "function" for s in created.scorers)
    metadata = json.loads(created.metadata.to_json())
    assert metadata["candidate_label"] == "fixture"
    assert metadata["judge_included"] is False
    assert "not a trained-model result" in metadata["note"]

    run_request = world.requests_named("create_evaluation_run")[0]
    assert run_request.evaluation_id == EVALUATION_ID
    assert json.loads(run_request.metadata.to_json()) == {"candidate_label": "fixture"}
    assert world.requests_named("get_dataset_revision_download_links")[0].revision_id == (
        "result-revision-1"
    )

    assert world.sleeps == [2.0, 2.0]
    assert result.transport == "injected_fixture"


def test_a_faithful_succeeded_run_is_usable_and_honest_about_what_it_is(
    world: ChalkWorld,
) -> None:
    result = run_adapter(world)
    assert result.usable is True and result.problems == []
    assert result.run_status == "succeeded"
    assert result.cloud_status_is_sufficient is False
    assert result.transport == "injected_fixture"
    assert result.expected_rows == result.result_rows == len(result.rows)
    assert result.parity_mismatches == []
    assert result.rows_with_task_error == result.rows_with_scorer_error == 0
    assert [s.dimension for s in result.scorers] == list(DIMENSIONS)
    assert all(s.mean == 1.0 and s.rows_errored == 0 for s in result.scorers)
    assert result.claims == {"trained_model_result": False, "learning_gain_claim": False}
    assert result.judged is None
    # Remote latency is never measured, and fixture latency stays missing.
    assert result.remote_latency_ms is None
    assert all(r.latency_ms is None and r.latency_source == "missing" for r in result.rows)
    assert result.dataset_revision == {"dataset_id": DATASET_ID, "revision_id": REVISION_ID}


def test_leaky_replies_score_low_without_being_reported_as_errors(
    world: ChalkWorld,
) -> None:
    result = run_adapter(world, candidate="leaky")
    assert result.usable is True
    disclosure = next(s for s in result.scorers if s.dimension == "disclosure")
    assert disclosure.mean is not None and disclosure.mean < 0.5
    assert disclosure.rows_errored == 0


def test_an_existing_suite_is_reused_not_recreated(world: ChalkWorld) -> None:
    from chalkcompute._gen.chalk.evaluation.v1 import service_pb as evaluation_pb

    world.suites.append(evaluation_pb.EvaluationSuite(id="suite-existing", name=CHALK_SUITE_NAME))
    run_adapter(world)
    assert "create_evaluation_suite" not in world.names()
    assert world.created_evaluation.suite_id == "suite-existing"


def test_functions_deploy_only_after_the_dataset_is_uploaded(world: ChalkWorld) -> None:
    world.http.put_status = 500
    with pytest.raises(DatasetError, match="HTTP 500"):
        run_adapter(world)
    assert world.names() == ["get_dataset_upload_uris"]
    assert world.function_loads == [] and world.deployments == []


# --- succeeded is not enough ------------------------------------------------------------


def corrupt(world: ChalkWorld, change: Any) -> None:
    world.mutate = change


def _set(columns: Columns, name: str, index: int, value: Any) -> Columns:
    columns[name][index] = value
    return columns


def test_a_task_error_on_a_succeeded_run_makes_it_unusable(world: ChalkWorld) -> None:
    def change(columns: Columns) -> Columns:
        columns["output"][1] = None
        columns["output_error"][1] = "task exploded Authorization: Bearer inert-canary-0123456789"
        return columns

    corrupt(world, change)
    result = run_adapter(world)
    assert result.run_status == "succeeded"
    assert result.usable is False
    assert result.rows_with_task_error == 1
    assert any("task error" in p for p in result.problems)
    assert "inert-canary" not in result.model_dump_json()
    assert result.rows[1].output_error is not None


def test_empty_task_output_without_an_error_is_still_a_task_failure(
    world: ChalkWorld,
) -> None:
    corrupt(world, lambda c: _set(c, "output", 0, ""))
    result = run_adapter(world)
    assert result.usable is False and result.rows_with_task_error == 1
    assert result.rows[0].output_error == "task produced no output"


def test_a_scorer_error_on_a_succeeded_run_is_reported_per_row_and_scorer(
    world: ChalkWorld,
) -> None:
    scorer = SCORER_FUNCTION_NAMES["respect"]

    def change(columns: Columns) -> Columns:
        columns[f"{scorer}_value"][2] = None
        columns[f"{scorer}_error"][2] = "ValueError: scorer crashed"
        return columns

    corrupt(world, change)
    result = run_adapter(world)
    assert result.run_status == "succeeded" and result.usable is False
    assert result.rows_with_scorer_error == 1
    assert result.rows[2].scorer_errors == {"respect": "ValueError: scorer crashed"}
    respect = next(s for s in result.scorers if s.dimension == "respect")
    assert respect.rows_errored == 1
    assert respect.rows_scored == result.result_rows - 1
    assert result.rows[2].scores["respect"] is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1.5, -0.1])
def test_a_non_finite_or_out_of_range_score_is_an_error_not_a_score(
    world: ChalkWorld,
    bad: float,
) -> None:
    scorer = SCORER_FUNCTION_NAMES["math"]
    corrupt(world, lambda c: _set(c, f"{scorer}_value", 0, bad))
    result = run_adapter(world)
    assert result.usable is False
    assert result.rows[0].scorer_errors["math"] == "score is not a finite number in [0, 1]"
    assert result.rows[0].scores["math"] is None


def test_a_remote_score_that_differs_from_the_local_rubric_is_a_parity_problem(
    world: ChalkWorld,
) -> None:
    scorer = SCORER_FUNCTION_NAMES["respect"]
    corrupt(world, lambda c: _set(c, f"{scorer}_value", 0, 0.25))
    result = run_adapter(world)
    assert result.usable is False
    assert len(result.parity_mismatches) == 1
    assert "respect remote=0.25 local=1.0" in result.parity_mismatches[0]


def test_a_score_where_the_local_rubric_has_none_is_a_parity_problem(
    world: ChalkWorld,
) -> None:
    _, report = replay()
    index = next(i for i, row in enumerate(report.rows) if row.scores[0].value is None)
    scorer = SCORER_FUNCTION_NAMES["math"]
    corrupt(world, lambda c: _set(c, f"{scorer}_value", index, 1.0))
    result = run_adapter(world)
    assert result.usable is False
    assert any("math remote=1.0 local=None" in m for m in result.parity_mismatches)


@pytest.mark.parametrize(
    "column",
    [
        "output",
        "output_error",
        "row_id",
        f"{SCORER_FUNCTION_NAMES['math']}_value",
        f"{SCORER_FUNCTION_NAMES['math']}_error",
    ],
)
def test_a_missing_result_column_is_a_problem(world: ChalkWorld, column: str) -> None:
    def change(columns: Columns) -> Columns:
        columns.pop(column)
        return columns

    corrupt(world, change)
    result = run_adapter(world)
    assert result.usable is False
    assert f"result is missing column {column}" in result.problems


def test_a_short_result_table_names_the_absent_rows(world: ChalkWorld) -> None:
    def change(columns: Columns) -> Columns:
        return {name: values[:-1] for name, values in columns.items()}

    corrupt(world, change)
    result = run_adapter(world)
    assert result.usable is False
    assert result.result_rows == result.expected_rows - 1
    assert any(p.startswith("expected") for p in result.problems)
    assert any(p.startswith("rows absent from the result") for p in result.problems)


# --- run lifecycle ----------------------------------------------------------------------


def test_a_failed_run_is_unusable_and_its_results_are_never_read(world: ChalkWorld) -> None:
    world.poll_statuses = ["RUNNING", "FAILED"]
    world.run_error_message = "worker crashed: secret=inert-canary-value-123456"
    result = run_adapter(world)
    assert result.run_status == "failed" and result.usable is False
    assert result.result_rows == 0 and result.result_dataset is None
    assert "run status is failed" in result.problems
    assert "inert-canary" not in result.model_dump_json()
    assert "get_dataset_revision_download_links" not in world.names()


def test_a_canceled_run_is_unusable(world: ChalkWorld) -> None:
    world.poll_statuses = ["CANCELED"]
    result = run_adapter(world)
    assert result.run_status == "canceled" and result.usable is False


def test_a_run_that_outlives_the_timeout_raises_and_reads_nothing(world: ChalkWorld) -> None:
    world.poll_statuses = ["RUNNING"]
    with pytest.raises(TimeoutError, match="may still be running"):
        run_adapter(world, chalk_settings(chalk_run_timeout_seconds=0.05))
    assert "get_dataset_revision_download_links" not in world.names()
    assert world.sleeps


def test_an_rpc_failure_surfaces_the_sdk_error_and_stops_the_sequence(
    world: ChalkWorld,
) -> None:
    world.rpc_errors["create_evaluation"] = rpc_error(Code.PERMISSION_DENIED, "no evaluations")
    with pytest.raises(EvaluationError, match="no evaluations") as caught:
        run_adapter(world)
    assert caught.value.status_code == 403
    assert "create_evaluation_run" not in world.names()


def test_an_upload_rpc_failure_stops_before_any_function_is_loaded(
    world: ChalkWorld,
) -> None:
    world.rpc_errors["finalize_dataset_upload"] = rpc_error(Code.UNAVAILABLE, "try later")
    with pytest.raises(DatasetError, match="try later"):
        run_adapter(world)
    assert world.function_loads == [] and world.deployments == []


# --- judge ------------------------------------------------------------------------------


def test_a_requested_judge_is_loaded_pinned_and_reported_apart_from_the_rubric(
    world: ChalkWorld,
) -> None:
    world.judge_in_results = True
    result = run_adapter(world, judge_settings(), include_judge=True)
    assert world.function_loads == [(True, JUDGE_MODEL)]
    assert os.environ.get("TUTORING_EVAL_JUDGE_MODEL") == JUDGE_MODEL
    assert len(world.created_evaluation.scorers) == len(DIMENSIONS) + 1
    assert json.loads(world.created_evaluation.metadata.to_json())["judge_included"] is True
    assert result.usable is True
    assert result.judged is not None
    assert result.judged["kind"] == "model_judged"
    assert result.judged["scorer"] == JUDGE_SCORER_NAME
    assert result.judged["rated_rows"] == result.result_rows
    # The judge never feeds the deterministic scorer list.
    assert [s.dimension for s in result.scorers] == list(DIMENSIONS)
    assert all(s.mean == 1.0 for s in result.scorers)


def test_a_missing_judge_column_makes_a_judged_run_unusable(world: ChalkWorld) -> None:
    result = run_adapter(world, judge_settings(), include_judge=True)
    assert result.usable is False
    assert f"result is missing column {JUDGE_SCORER_NAME}_value" in result.problems


def test_judge_errors_are_counted_and_do_not_change_the_deterministic_scores(
    world: ChalkWorld,
) -> None:
    world.judge_in_results = True

    def change(columns: Columns) -> Columns:
        columns[f"{JUDGE_SCORER_NAME}_error"][0] = "model unavailable"
        columns[f"{JUDGE_SCORER_NAME}_value"][0] = None
        return columns

    corrupt(world, change)
    result = run_adapter(world, judge_settings(), include_judge=True)
    assert result.judged is not None
    assert result.judged["errored_rows"] == 1
    assert result.judged["rated_rows"] == result.result_rows - 1
    assert all(s.mean == 1.0 for s in result.scorers)


# --- credentials and environment --------------------------------------------------------


def test_sdk_credentials_are_set_only_inside_the_block_and_restored_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHALK_CLIENT_ID", "preexisting-id")
    monkeypatch.delenv("CHALK_API_SERVER", raising=False)
    settings = chalk_settings(chalk_api_server="https://api.chalk.ai")
    with _sdk_credentials(settings):
        assert os.environ["CHALK_CLIENT_ID"] == FIXTURE_CLIENT_ID
        assert os.environ["CHALK_CLIENT_SECRET"] == FIXTURE_CLIENT_SECRET
        assert os.environ["CHALK_ENVIRONMENT"] == "fixture-environment"
        assert os.environ["CHALK_API_SERVER"] == "https://api.chalk.ai"
    assert os.environ["CHALK_CLIENT_ID"] == "preexisting-id"
    assert "CHALK_CLIENT_SECRET" not in os.environ
    assert "CHALK_ENVIRONMENT" not in os.environ
    assert "CHALK_API_SERVER" not in os.environ


def test_sdk_credentials_are_restored_when_the_block_raises() -> None:
    with pytest.raises(RuntimeError), _sdk_credentials(chalk_settings()):
        raise RuntimeError("boom")
    assert "CHALK_CLIENT_SECRET" not in os.environ


def test_the_secret_never_reaches_a_request_message_or_the_report(world: ChalkWorld) -> None:
    result = run_adapter(world)
    blob = result.model_dump_json() + "".join(repr(rpc.request) for rpc in world.rpcs)
    assert FIXTURE_CLIENT_SECRET not in blob and FIXTURE_CLIENT_ID not in blob


# --- CLI --------------------------------------------------------------------------------


def _cli(monkeypatch: pytest.MonkeyPatch, settings: Settings, *argv: str) -> int:
    from app.cli import main

    monkeypatch.setattr(eval_cli, "get_settings", lambda: settings)
    return main(["evaluation", *argv])


def test_cli_status_and_cases_and_run_and_plan_are_local(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[tuple[str, object]],
) -> None:
    settings = chalk_settings()
    assert _cli(monkeypatch, settings, "status") == 0
    assert json.loads(capsys.readouterr().out)["state"] == "configured_unverified"
    assert _cli(monkeypatch, settings, "cases") == 0
    cases = json.loads(capsys.readouterr().out)
    assert cases["is_fictional"] is True
    assert all(
        not [i for i in t["visible_source_ids"] if i.startswith("future.")] for t in cases["turns"]
    )
    assert _cli(monkeypatch, settings, "run", "--candidate", "fixture:good") == 0
    run = json.loads(capsys.readouterr().out)
    assert run["candidate_label"] == "fixture"
    assert run["claims"]["trained_model_result"] is False
    assert run["latency_mean_ms"] is None
    assert _cli(monkeypatch, settings, "chalk-plan") == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["plan"]["row_count"] == 9
    assert "Nothing was uploaded" in plan["note"]
    assert no_network == []


def test_cli_chalk_run_refuses_without_confirm_live_even_when_fully_configured(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    world: ChalkWorld,
) -> None:
    monkeypatch.setattr(
        eval_cli, "ChalkEvaluationAdapter", lambda settings: pytest.fail("adapter was built")
    )
    assert _cli(monkeypatch, chalk_settings(), "chalk-run") == 2
    output = json.loads(capsys.readouterr().out)
    assert "refused" in output and output["status"]["state"] == "configured_unverified"
    assert world.rpcs == []


def test_cli_chalk_run_with_confirm_live_reports_the_normalized_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    world: ChalkWorld,
) -> None:
    settings = chalk_settings()
    monkeypatch.setattr(
        eval_cli, "ChalkEvaluationAdapter", lambda s: ChalkEvaluationAdapter(s, world.seams())
    )
    assert _cli(monkeypatch, settings, "chalk-run", "--confirm-live", "--name", "cli-eval") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["usable"] is True and output["transport"] == "injected_fixture"
    assert world.created_evaluation.name == "cli-eval"


def test_cli_exit_code_is_nonzero_when_a_succeeded_run_has_row_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    world: ChalkWorld,
) -> None:
    corrupt(world, lambda c: _set(c, "output_error", 0, "boom"))
    monkeypatch.setattr(
        eval_cli, "ChalkEvaluationAdapter", lambda s: ChalkEvaluationAdapter(s, world.seams())
    )
    assert _cli(monkeypatch, chalk_settings(), "chalk-run", "--confirm-live") == 1
    output = json.loads(capsys.readouterr().out)
    assert output["run_status"] == "succeeded" and output["usable"] is False


def test_cli_redacts_a_provider_error_and_lists_the_requests_already_sent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    world: ChalkWorld,
) -> None:
    world.rpc_errors["create_evaluation"] = rpc_error(
        Code.INTERNAL, "failed secret=inert-canary-value-123456"
    )
    monkeypatch.setattr(
        eval_cli, "ChalkEvaluationAdapter", lambda s: ChalkEvaluationAdapter(s, world.seams())
    )
    assert _cli(monkeypatch, chalk_settings(), "chalk-run", "--confirm-live") == 1
    text = capsys.readouterr().out
    assert "inert-canary" not in text
    assert "dataset_upload" in json.loads(text)["requests_sent"]


def test_cli_confirm_live_while_disabled_is_refused_with_no_requests(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    world: ChalkWorld,
) -> None:
    monkeypatch.setattr(
        eval_cli, "ChalkEvaluationAdapter", lambda s: ChalkEvaluationAdapter(s, world.seams())
    )
    disabled = Settings.model_validate({"database_url": "sqlite://"})
    assert _cli(monkeypatch, disabled, "chalk-run", "--confirm-live") == 2
    assert "disabled" in json.loads(capsys.readouterr().out)["refused"]
    assert world.rpcs == [] and world.deployments == []


def test_cli_rejects_a_bad_responses_file_without_echoing_its_contents(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("Authorization: Bearer inert-canary-0123456789abcdef not json")
    code = _cli(monkeypatch, chalk_settings(), "run", "--responses-file", str(path))
    assert code == 1
    assert "inert-canary" not in capsys.readouterr().out


# --- import and health isolation (fresh interpreters) -----------------------------------


def _probe(code: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CHALK_", "TUTORING_EVAL"))
        and key != "EXTERNAL_INTEGRATIONS_ENABLED"
    }
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_importing_the_adapter_cli_and_app_loads_no_chalk_sdk_and_deploys_nothing(
    tmp_path: Path,
) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    probe = (
        "import sys\n"
        "import app.main, app.cli, app.tutoring_eval.chalk_adapter, app.tutoring_eval.cli\n"
        "from fastapi.testclient import TestClient\n"
        "from app.config import Settings\n"
        "from app.main import create_app\n"
        "client = TestClient(create_app(Settings(database_url='sqlite://')))\n"
        "assert client.get('/health').status_code == 200\n"
        "app.cli.build_parser()\n"
        "assert app.cli.main(['evaluation', 'status']) == 0\n"
        "assert app.cli.main(['evaluation', 'chalk-plan']) == 0\n"
        "assert app.cli.main(['evaluation', 'chalk-run']) == 2\n"
        "assert app.cli.main(['evaluation', 'chalk-run', '--confirm-live']) == 2\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'chalkcompute', 'pyarrow', 'torch', 'transformers', 'anthropic'} "
        "or m.startswith('app.tutoring_eval.chalk_functions') "
        "or m.startswith('app.tutoring_eval.chalk_judge'))\n"
        "print('LOADED=' + ','.join(loaded))\n"
    )
    result = _probe(probe, env={"TUTOR_ENV_FILE": str(empty_env)})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "LOADED="


def test_a_configured_but_unconfirmed_or_judge_less_run_loads_no_sdk(tmp_path: Path) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    probe = (
        "import sys, app.cli\n"
        "assert app.cli.main(['evaluation', 'chalk-run']) == 2\n"
        "assert app.cli.main(\n"
        "    ['evaluation', 'chalk-run', '--confirm-live', '--include-judge']) == 2\n"
        "print('chalkcompute' in sys.modules, "
        "'app.tutoring_eval.chalk_functions' in sys.modules)\n"
    )
    env = {
        "TUTOR_ENV_FILE": str(empty_env),
        "EXTERNAL_INTEGRATIONS_ENABLED": "true",
        "CHALK_EVALUATIONS_ENABLED": "true",
        "CHALK_CLIENT_ID": FIXTURE_CLIENT_ID,
        "CHALK_CLIENT_SECRET": FIXTURE_CLIENT_SECRET,
        "CHALK_ENVIRONMENT": "fixture-environment",
    }
    result = _probe(probe, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False False"
    assert FIXTURE_CLIENT_SECRET not in result.stdout + result.stderr
