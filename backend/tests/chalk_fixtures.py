"""A Chalk Compute transport fixture that answers with the SDK's own protobuf messages.

The adapter under test drives the installed ``chalkcompute`` ``DatasetClient`` and
``EvaluationClient`` for real. Only the two seams below them are replaced:

* ``FakeConnect`` stands in for ``ConnectClient`` (``stub`` and ``call``) and answers each
  ConnectRPC method with real generated request/response messages.
* ``FakeHttp`` stands in for the signed-URL HTTP client used for parquet upload and download.

Result tables are produced by running the real scorer functions defined in
``app.tutoring_eval.chalk_functions`` locally, so a "faithful" cloud really does reproduce the
local rubric, and each failure test then corrupts that table in one specific way.

None of this is Chalk. A run through it is labeled ``injected_fixture``; it says nothing
about a live account, queue enablement, cost or latency.
"""

import io
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from chalkcompute._gen.chalk.evaluation.v1 import service_pb as evaluation_pb
from chalkcompute._gen.chalk.server.v1 import datasets_pb
from chalkcompute._gen.chalk.volume.v1 import volume_pb
from connectrpc.code import Code
from connectrpc.errors import ConnectError
from protobuf import Oneof

from app.config import Settings
from app.tutoring_eval.chalk_adapter import (
    JUDGE_SCORER_NAME,
    SCORER_FUNCTION_NAMES,
    ChalkSeams,
    RemoteFunctions,
)
from app.tutoring_eval.contracts import DIMENSIONS

UPLOAD_URL = "https://uploads.example.invalid/session-1"
RESULT_URL = "https://downloads.example.invalid/result-1.parquet"
DATASET_ID = "dataset-1"
REVISION_ID = "revision-1"
RESULT_DATASET_ID = "result-dataset-1"
RESULT_REVISION_ID = "result-revision-1"
RUN_ID = "run-1"
EVALUATION_ID = "evaluation-1"
SUITE_ID = "suite-1"
# Visibly inert placeholders: not shaped like any provider credential.
FIXTURE_CLIENT_ID = "fixture-client-id-inert"
FIXTURE_CLIENT_SECRET = "fixture-client-secret-INERT-CANARY"  # noqa: S105

Columns = dict[str, list[Any]]


@dataclass
class RecordedRpc:
    name: str
    request: Any


@dataclass
class FakeResponse:
    status: int = 200
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    trailers: dict[str, str] = field(default_factory=dict)


class FakeHttp:
    """The upload/download HTTP client: PUT stores bytes, GET returns scripted bytes."""

    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}
        self.downloads: dict[str, bytes] = {}
        self.put_status = 200
        self.requests: list[tuple[str, str]] = []

    def put(
        self, url: str, headers: Any = None, content: Any = None, *, timeout: Any = None
    ) -> FakeResponse:
        self.requests.append(("PUT", url))
        body = content if isinstance(content, bytes) else b"".join(content or [])
        if not 200 <= self.put_status < 300:
            return FakeResponse(status=self.put_status, content=b"storage said no")
        self.uploads[url] = body
        return FakeResponse()

    def get(self, url: str, headers: Any = None, *, timeout: Any = None) -> FakeResponse:
        self.requests.append(("GET", url))
        if url not in self.downloads:
            return FakeResponse(status=404, content=b"missing")
        return FakeResponse(content=self.downloads[url])

    def post(self, *args: Any, **kwargs: Any) -> FakeResponse:  # pragma: no cover - unused
        raise AssertionError("the adapter must not POST to a signed URL")


class FakeConnect:
    """``ConnectClient`` replacement: ``stub`` names an RPC, ``call`` invokes it like the SDK."""

    def __init__(self, world: "ChalkWorld") -> None:
        self._world = world
        self.stub_classes: list[str] = []

    def stub(self, stub_cls: Callable[..., Any]) -> Any:
        self.stub_classes.append(getattr(stub_cls, "__name__", str(stub_cls)))
        world = self._world

        class Stub:
            def __getattr__(self, name: str) -> Callable[..., Any]:
                def rpc(request: Any, *, timeout_ms: int | None = None, headers: Any = None) -> Any:
                    world.rpcs.append(RecordedRpc(name, request))
                    if name in world.rpc_errors:
                        raise world.rpc_errors[name]
                    return getattr(world, f"_rpc_{name}")(request)

                rpc.__name__ = name
                return rpc

        return Stub()

    def call(
        self,
        method: Callable[..., Any],
        request: Any,
        *,
        timeout: float = 30.0,
        extra_headers: Any = None,
    ) -> Any:
        return method(request, timeout_ms=round(timeout * 1000), headers=dict(extra_headers or {}))


def faithful_result(world: "ChalkWorld", dataset: pa.Table) -> Columns:
    """What a healthy cloud writes: dataset columns plus task output and scorer columns."""
    functions = world.functions
    assert functions is not None, "functions must be loaded before a result can be produced"
    columns: Columns = {name: dataset[name].to_pylist() for name in dataset.column_names}
    outputs = [str(functions.task(text)) for text in columns["candidate_text"]]
    columns["output"] = outputs
    columns["output_error"] = [None] * len(outputs)
    for dimension in DIMENSIONS:
        scorer = SCORER_FUNCTION_NAMES[dimension]
        values: list[float | None] = []
        for index, output in enumerate(outputs):
            results = functions.scorers[dimension](
                output,
                columns["rubric_context_json"][index],
                columns["cited_source_ids_json"][index],
                columns["answer_revealed_claim"][index],
            )
            values.append(results[0].score if results else None)
        columns[f"{scorer}_value"] = values
        columns[f"{scorer}_error"] = [None] * len(outputs)
        columns[f"{scorer}_metadata"] = [None] * len(outputs)
    if world.judge_in_results:
        columns[f"{JUDGE_SCORER_NAME}_value"] = [0.5] * len(outputs)
        columns[f"{JUDGE_SCORER_NAME}_error"] = [None] * len(outputs)
    return columns


def table_from_columns(columns: Columns) -> pa.Table:
    arrays = {}
    for name, values in columns.items():
        if name.endswith("_value") or name == "local_latency_ms":
            arrays[name] = pa.array(values, type=pa.float64())
        elif name == "omitted_future_events":
            arrays[name] = pa.array(values, type=pa.int64())
        else:
            arrays[name] = pa.array(values, type=pa.string())
    return pa.table(arrays)


class ChalkWorld:
    """Scripted cloud state plus the seams to hand to the adapter."""

    def __init__(self) -> None:
        self.rpcs: list[RecordedRpc] = []
        self.rpc_errors: dict[str, Exception] = {}
        self.http = FakeHttp()
        self.connect = FakeConnect(self)
        self.sleeps: list[float] = []
        self.suites: list[evaluation_pb.EvaluationSuite] = []
        self.dataset_table: pa.Table | None = None
        self.dataset_name: str | None = None
        self.created_evaluation: Any = None
        self.created_scorers: list[Any] = []
        # Statuses returned by successive polls after the run is created as PENDING.
        self.poll_statuses: list[str] = ["RUNNING", "SUCCEEDED"]
        self.run_error_message = ""
        self.result_builder: Callable[[ChalkWorld, pa.Table], Columns] = faithful_result
        self.mutate: Callable[[Columns], Columns] | None = None
        self.functions: RemoteFunctions | None = None
        self.function_loads: list[tuple[bool, str | None]] = []
        self.judge_in_results = False
        self.deployments: list[str] = []
        self.uploaded_count = 0

    # --- seams ---------------------------------------------------------------------------

    def seams(self) -> ChalkSeams:
        return ChalkSeams(
            connect_client=self.connect,
            http_client=self.http,
            function_loader=self.load_functions,
            sleep=self.sleeps.append,
        )

    def names(self) -> list[str]:
        return [rpc.name for rpc in self.rpcs]

    def requests_named(self, name: str) -> list[Any]:
        return [rpc.request for rpc in self.rpcs if rpc.name == name]

    # --- function loading (real RemoteFunction objects, deployment itself stubbed) -------

    def load_functions(self, include_judge: bool, judge_model: str | None) -> RemoteFunctions:
        self.function_loads.append((include_judge, judge_model))
        from app.tutoring_eval import chalk_adapter

        loaded = chalk_adapter.load_remote_functions(include_judge, judge_model)
        for index, function in enumerate([loaded.task, *loaded.scorers.values(), loaded.judge]):
            if function is None:
                continue
            from chalkcompute._function import FunctionVersionInfo

            name = getattr(function, "_func_name", f"function-{index}")
            function._version_info = FunctionVersionInfo(
                id=f"function-version-{name}",
                function_name=name,
                version=1,
                scaling_group_name="fixture-scaling-group",
            )
        self.functions = loaded
        return loaded

    # --- RPC handlers (names match the generated ConnectRPC clients) ---------------------

    def _rpc_get_dataset_upload_uris(self, request: Any) -> Any:
        return datasets_pb.GetDatasetUploadUrisResponse(
            upload_session_id="session-1",
            upload=Oneof("direct", volume_pb.DirectUpload(signed_upload_uri=UPLOAD_URL)),
        )

    def _rpc_finalize_dataset_upload(self, request: Any) -> Any:
        self.dataset_name = request.dataset_name
        self.dataset_table = pq.read_table(io.BytesIO(self.http.uploads[UPLOAD_URL]))
        self.uploaded_count += 1
        revision = datasets_pb.DatasetRevisionMeta(
            offline_query_id=REVISION_ID, dataset_id=DATASET_ID
        )
        meta = datasets_pb.DatasetMeta(
            id=DATASET_ID, dataset_name=request.dataset_name, most_recent_revision=revision
        )
        return datasets_pb.FinalizeDatasetUploadResponse(dataset=meta)

    def _rpc_get_dataset_revision_download_links(self, request: Any) -> Any:
        assert request.revision_id == RESULT_REVISION_ID, request.revision_id
        assert self.dataset_table is not None
        columns = self.result_builder(self, self.dataset_table)
        if self.mutate is not None:
            columns = self.mutate(columns)
        buffer = io.BytesIO()
        pq.write_table(table_from_columns(columns), buffer)
        self.http.downloads[RESULT_URL] = buffer.getvalue()
        return datasets_pb.GetDatasetRevisionDownloadLinksResponse(output_urls=[RESULT_URL])

    def _rpc_list_evaluation_suites(self, request: Any) -> Any:
        return evaluation_pb.ListEvaluationSuitesResponse(suites=list(self.suites))

    def _rpc_create_evaluation_suite(self, request: Any) -> Any:
        suite = evaluation_pb.EvaluationSuite(id=SUITE_ID, name=request.name)
        self.suites.append(suite)
        return evaluation_pb.CreateEvaluationSuiteResponse(suite=suite)

    def _rpc_create_evaluation(self, request: Any) -> Any:
        self.created_evaluation = request
        scorers = [
            evaluation_pb.EvaluationScorer(id=f"scorer-{i}", spec=spec)
            for i, spec in enumerate(request.scorers)
        ]
        self.created_scorers = scorers
        evaluation = evaluation_pb.Evaluation(
            id=EVALUATION_ID,
            name=request.name,
            dataset_id=request.dataset_id,
            dataset_revision_id=request.dataset_revision_id,
            task_function_version_id=request.task_function_version_id,
            scorers=scorers,
            suite_id=request.suite_id or "",
        )
        return evaluation_pb.CreateEvaluationResponse(evaluation=evaluation)

    def _run_message(self, status_name: str) -> Any:
        status = getattr(evaluation_pb.EvaluationRunStatus, status_name)
        done = status_name == "SUCCEEDED"
        return evaluation_pb.EvaluationRun(
            id=RUN_ID,
            evaluation_id=EVALUATION_ID,
            status=status,
            result_dataset_id=RESULT_DATASET_ID if done else "",
            result_dataset_revision_id=RESULT_REVISION_ID if done else "",
            error_message=self.run_error_message if status_name == "FAILED" else "",
        )

    def _rpc_create_evaluation_run(self, request: Any) -> Any:
        return evaluation_pb.CreateEvaluationRunResponse(
            evaluation_run=self._run_message("PENDING")
        )

    def _rpc_get_evaluation_run(self, request: Any) -> Any:
        status = self.poll_statuses.pop(0) if len(self.poll_statuses) > 1 else self.poll_statuses[0]
        return evaluation_pb.GetEvaluationRunResponse(evaluation_run=self._run_message(status))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_rpc_"):
            raise AssertionError(f"the adapter called an RPC the fixture does not model: {name}")
        raise AttributeError(name)


def rpc_error(code: Code = Code.PERMISSION_DENIED, message: str = "denied") -> ConnectError:
    return ConnectError(code, message)


def chalk_settings(**overrides: object) -> Settings:
    """Settings that pass every activation check, using inert placeholder credentials."""
    values: dict[str, object] = {
        "database_url": "sqlite://",
        "external_integrations_enabled": True,
        "chalk_evaluations_enabled": True,
        "chalk_client_id": FIXTURE_CLIENT_ID,
        "chalk_client_secret": FIXTURE_CLIENT_SECRET,
        "chalk_environment": "fixture-environment",
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[ChalkWorld]:
    """A cloud fixture with function deployment stubbed so no definition ever deploys."""
    import chalkcompute._function as function_module

    cloud = ChalkWorld()

    def no_deploy(function: Any) -> Future[None]:
        cloud.deployments.append(str(getattr(function, "_func_name", function)))
        finished: Future[None] = Future()
        finished.set_result(None)
        return finished

    monkeypatch.setattr(function_module, "_schedule_background_deployment", no_deploy)
    # Re-import the deploying modules for this test only, then leave no trace of them.
    for module in ("app.tutoring_eval.chalk_functions", "app.tutoring_eval.chalk_judge"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    # The judge module reads its model from the environment; setenv first so teardown restores
    # the variable to absent even after the adapter sets it.
    monkeypatch.setenv("TUTORING_EVAL_JUDGE_MODEL", "")
    monkeypatch.delenv("TUTORING_EVAL_JUDGE_MODEL")
    yield cloud
    for module in ("app.tutoring_eval.chalk_functions", "app.tutoring_eval.chalk_judge"):
        sys.modules.pop(module, None)
