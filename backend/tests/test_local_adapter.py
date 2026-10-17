"""The production local Transformers adapter, driven at its loader/generator boundary.

The adapter, its factory and readiness are the production objects. Only the model itself is
instrumented (counting loads and generations), because the pinned SmolLM2 weights are never
downloaded here. Pretrained execution is therefore *not* claimed by these tests; the real
Transformers generation path is exercised separately with a tiny random-weight model in
``test_hf_transformers.py``. Outbound sockets are blocked throughout.
"""

import asyncio
import contextlib
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import Database
from app.inference import factory
from app.inference.cancel import CancelToken
from app.inference.errors import (
    DeviceUnavailableError,
    MalformedDraftError,
    ModelLoadError,
    ProviderBusyError,
    ProviderCancelledError,
    ProviderDisabledError,
    ProviderTimeoutError,
    RequestTooLargeError,
    StaleDraftError,
    TruncatedDraftError,
)
from app.inference.local import (
    GenerationOutput,
    LocalModel,
    LocalModelConfig,
    LocalTransformersAdapter,
)
from app.inference.providers import DraftInputs
from app.inference.request import ProviderMessage
from app.main import create_app
from tests.provider_fixtures import (
    TURN_ID,
    make_inputs,
    valid_draft_json,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def config(**overrides: object) -> LocalModelConfig:
    values: dict[str, object] = {
        "model_id": "HuggingFaceTB/SmolLM2-135M-Instruct",
        "revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
        "device": "cpu",
        "dtype": "float32",
        "allow_download": False,
        "context_window_tokens": 8_192,
        "max_new_tokens": 512,
        "max_queue": 1,
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return LocalModelConfig(**values)  # type: ignore[arg-type]


class FakeModel:
    """Counts generations and lets a test hold, slow or script each one."""

    def __init__(
        self,
        reply: Callable[[list[ProviderMessage]], str],
        *,
        prompt_tokens: int = 100,
        fragments: int = 3,
    ) -> None:
        self.reply = reply
        self.prompt_tokens = prompt_tokens
        self.fragments = fragments
        self.generations = 0
        self.seen_max_new: list[int] = []
        self.entered = threading.Event()
        self.release: threading.Event | None = None
        self.honor_stop = True
        self.hit_length_limit = False
        self.stopped_early = False

    def count_prompt_tokens(self, messages: list[ProviderMessage]) -> int:
        return self.prompt_tokens

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        max_new_tokens: int,
        should_stop: Callable[[], bool],
        on_text: Callable[[str], None],
    ) -> GenerationOutput:
        self.generations += 1
        self.seen_max_new.append(max_new_tokens)
        self.entered.set()
        text = self.reply(messages)
        step = max(1, len(text) // self.fragments)
        for start in range(0, len(text), step):
            if self.honor_stop and should_stop():
                self.stopped_early = True
                break
            on_text(text[start : start + step])
            if self.release is not None and start == 0:
                assert self.release.wait(timeout=10), "test never released the generation"
        return GenerationOutput(
            text=text, output_tokens=len(text) // 4 + 1, hit_length_limit=self.hit_length_limit
        )


class CountingLoader:
    def __init__(self, model: LocalModel | Exception) -> None:
        self.model = model
        self.calls: list[LocalModelConfig] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, cfg: LocalModelConfig) -> LocalModel:
        with self.lock:
            self.calls.append(cfg)
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(timeout=10)
        if isinstance(self.model, Exception):
            raise self.model
        return self.model


@pytest.fixture(autouse=True)
def _blocked(no_network: list) -> list:
    return no_network


@pytest.fixture
def inputs(database: Database) -> DraftInputs:
    return make_inputs(database)


@pytest.fixture
def adapters() -> Iterator[list[LocalTransformersAdapter]]:
    made: list[LocalTransformersAdapter] = []
    yield made
    for adapter in made:
        adapter.close()


def build(
    adapters: list[LocalTransformersAdapter],
    loader: Callable[[LocalModelConfig], LocalModel],
    **overrides: object,
) -> LocalTransformersAdapter:
    adapter = LocalTransformersAdapter(config(**overrides), loader)
    adapters.append(adapter)
    return adapter


def good_reply(inputs: DraftInputs) -> Callable[[list[ProviderMessage]], str]:
    text = valid_draft_json(inputs)
    return lambda messages: text


class TestNoLoadAtImportConfigOrHealth:
    def test_importing_modules_and_serving_health_loads_no_model_library(self) -> None:
        # A fresh interpreter, because this process may already have imported torch.
        code = (
            "import sys\n"
            "from fastapi.testclient import TestClient\n"
            "from app.config import Settings\n"
            "from app.main import create_app\n"
            "import app.inference.hf_transformers, app.inference.factory, app.inference.readiness\n"
            "s = Settings.model_validate({'database_url': 'sqlite://', "
            "'tutor_provider': 'transformers', 'tutor_local_model_load_enabled': True})\n"
            "c = TestClient(create_app(s))\n"
            "assert c.get('/health').status_code == 200\n"
            "body = c.get('/health/model').json()\n"
            "assert body['state'] == 'not_loaded', body\n"
            "bad = [m for m in ('torch', 'transformers', 'huggingface_hub') if m in sys.modules]\n"
            "assert not bad, bad\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_building_the_adapter_and_reading_readiness_never_calls_the_loader(
        self, monkeypatch: pytest.MonkeyPatch, no_network: list
    ) -> None:
        loader = CountingLoader(RuntimeError("must not be called"))
        monkeypatch.setattr("app.inference.hf_transformers.load_transformers_model", loader)
        factory.reset_adapters()
        settings = Settings.model_validate(
            {
                "database_url": "sqlite://",
                "tutor_provider": "transformers",
                "tutor_local_model_load_enabled": True,
            }
        )
        try:
            adapter = factory.adapter_for(settings)
            assert adapter.name == "transformers"
            from app.inference.readiness import describe_model_readiness

            readiness = describe_model_readiness(settings)
            assert (readiness.state, readiness.ready) == ("not_loaded", False)
            assert loader.calls == []
            assert no_network == []
        finally:
            factory.reset_adapters()

    def test_loading_is_disabled_by_default_and_raises_a_typed_error(self) -> None:
        factory.reset_adapters()
        settings = Settings.model_validate(
            {"database_url": "sqlite://", "tutor_provider": "transformers"}
        )
        with pytest.raises(ProviderDisabledError) as caught:
            factory.adapter_for(settings)
        assert caught.value.code == "provider_disabled"
        assert "TUTOR_LOCAL_MODEL_LOAD_ENABLED" in str(caught.value)

    def test_local_adapter_label_says_it_runs_on_this_machine_and_not_a_mock(
        self, adapters: list[LocalTransformersAdapter]
    ) -> None:
        adapter = build(adapters, CountingLoader(RuntimeError("unused")))
        label = adapter.label()
        assert label.is_mock is False
        assert "runs on this machine" in label.label
        assert adapter.capabilities().transmission == "this_process"


class TestLazyLoadAndReuse:
    def test_first_draft_loads_once_and_later_drafts_reuse_the_model(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        loader = CountingLoader(model)
        adapter = build(adapters, loader)
        assert adapter.load_state == "not_loaded"
        assert loader.calls == []

        outcomes = [adapter.draft_outcome(inputs) for _ in range(3)]

        assert len(loader.calls) == 1
        assert adapter.stats.loads == 1
        assert adapter.load_state == "loaded"
        assert model.generations == 3
        assert all(o.draft.turn_id == TURN_ID for o in outcomes)
        assert next(e.kind for e in outcomes[0].events) == "started"
        assert outcomes[0].events[-1].kind == "completed"
        assert outcomes[0].attempts == 1

    def test_concurrent_first_use_loads_exactly_once(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        loader = CountingLoader(FakeModel(good_reply(inputs)))
        loader.gate = threading.Event()
        adapter = build(adapters, loader, max_queue=2)
        results: list[object] = []

        def call() -> None:
            results.append(adapter.draft_outcome(inputs).draft.turn_id)

        threads = [threading.Thread(target=call) for _ in range(3)]
        for thread in threads:
            thread.start()
        assert loader.entered.wait(timeout=10)
        loader.gate.set()
        for thread in threads:
            thread.join(timeout=15)
        assert results == [TURN_ID] * 3
        assert len(loader.calls) == 1

    def test_configured_model_revision_device_and_dtype_reach_the_loader(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        loader = CountingLoader(FakeModel(good_reply(inputs)))
        adapter = build(
            adapters, loader, model_id="org/other-model", revision="abc123", dtype="bfloat16"
        )
        adapter.draft_outcome(inputs)
        (seen,) = loader.calls
        assert (seen.model_id, seen.revision, seen.device, seen.dtype) == (
            "org/other-model",
            "abc123",
            "cpu",
            "bfloat16",
        )
        assert seen.allow_download is False

    def test_failed_load_is_typed_reported_and_retried_on_the_next_turn(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        loader = CountingLoader(OSError("/private/path/with/secrets is missing"))
        adapter = build(adapters, loader)
        with pytest.raises(ModelLoadError) as caught:
            adapter.draft_outcome(inputs)
        assert "/private/path" not in str(caught.value)
        assert adapter.load_state == "failed"
        assert adapter.last_load_failure == "model_load_failed"
        assert adapter.stats.loads == 0

        loader.model = FakeModel(good_reply(inputs))
        assert adapter.draft_outcome(inputs).draft.turn_id == TURN_ID
        assert len(loader.calls) == 2
        assert adapter.load_state == "loaded"
        assert adapter.last_load_failure is None

    def test_unavailable_device_error_keeps_its_own_code(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        loader = CountingLoader(DeviceUnavailableError("cuda was requested but is absent"))
        adapter = build(adapters, loader, device="cuda")
        with pytest.raises(DeviceUnavailableError):
            adapter.draft_outcome(inputs)
        assert adapter.last_load_failure == "device_unavailable"


class TestLimits:
    def test_prompt_plus_output_over_the_window_is_refused_before_any_generation(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs), prompt_tokens=300)
        adapter = build(adapters, CountingLoader(model), context_window_tokens=400)
        with pytest.raises(RequestTooLargeError):
            adapter.draft_outcome(inputs)
        assert model.generations == 0
        assert adapter.stats.generations_started == 0

    def test_exact_fit_is_accepted(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs), prompt_tokens=300)
        max_new = min(inputs.request.max_output_tokens, 100)
        adapter = build(
            adapters,
            CountingLoader(model),
            context_window_tokens=300 + max_new,
            max_new_tokens=100,
        )
        adapter.draft_outcome(inputs)
        assert model.seen_max_new == [max_new]

    def test_output_ceiling_is_the_smaller_of_request_and_configuration(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        adapter = build(adapters, CountingLoader(model), max_new_tokens=64)
        adapter.draft_outcome(inputs)
        assert model.seen_max_new == [min(inputs.request.max_output_tokens, 64)]

    def test_output_cut_off_by_the_token_limit_is_not_committed(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.hit_length_limit = True
        adapter = build(adapters, CountingLoader(model))
        with pytest.raises(TruncatedDraftError):
            adapter.draft_outcome(inputs)

    def test_queue_is_bounded_and_overflow_is_refused_immediately(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model), max_queue=1)
        outcomes: list[str] = []

        def call() -> None:
            try:
                outcomes.append(adapter.draft_outcome(inputs).draft.turn_id)
            except Exception as error:
                outcomes.append(type(error).__name__)

        running = threading.Thread(target=call)
        running.start()
        assert model.entered.wait(timeout=10)
        queued = threading.Thread(target=call)
        queued.start()
        deadline = time.monotonic() + 5
        while adapter._pending < 2 and time.monotonic() < deadline:
            time.sleep(0.005)

        started = time.monotonic()
        with pytest.raises(ProviderBusyError):
            adapter.draft_outcome(inputs)
        assert time.monotonic() - started < 1.0
        assert adapter.stats.refused_busy == 1

        model.release.set()
        running.join(timeout=15)
        queued.join(timeout=15)
        assert outcomes == [TURN_ID, TURN_ID]
        assert model.generations == 2

    def test_overlong_or_wrong_output_is_a_typed_rejection_not_a_repair(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        for text, error in (
            ("not json at all", MalformedDraftError),
            ('{"schema_version": "tutor-draft.v1"}', MalformedDraftError),
            (valid_draft_json(inputs, turn_id="some-other-turn"), StaleDraftError),
            (valid_draft_json(inputs, session_revision=99), StaleDraftError),
        ):
            adapter = build(adapters, CountingLoader(FakeModel(lambda _m, t=text: t)))
            with pytest.raises(error):
                adapter.draft_outcome(inputs)


class TestDeadlineAndCancel:
    def test_deadline_stops_a_cooperating_generation_and_nothing_commits(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs), fragments=40)
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model), timeout_seconds=0.2)
        with pytest.raises(ProviderTimeoutError):
            adapter.draft_outcome(inputs)
        model.release.set()
        _wait_for(lambda: adapter._pending == 0)
        assert model.stopped_early is True
        assert adapter.stats.late_results_discarded == 1

    def test_a_generator_that_ignores_stop_still_cannot_commit_late(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.honor_stop = False
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model), timeout_seconds=0.2)
        with pytest.raises(ProviderTimeoutError):
            adapter.draft_outcome(inputs)
        model.release.set()
        _wait_for(lambda: adapter._pending == 0)
        assert adapter.stats.late_results_discarded == 1

    def test_cancel_releases_the_caller_and_the_late_draft_is_discarded(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.honor_stop = False
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model))
        token = CancelToken()
        cancelling = DraftInputs(**{**inputs.__dict__, "cancel": token})
        raised: list[BaseException] = []

        def call() -> None:
            try:
                adapter.draft_outcome(cancelling)
            except BaseException as error:
                raised.append(error)

        thread = threading.Thread(target=call)
        thread.start()
        assert model.entered.wait(timeout=10)
        started = time.monotonic()
        token.cancel("user left")
        thread.join(timeout=5)
        assert time.monotonic() - started < 2.0
        assert [type(e) for e in raised] == [ProviderCancelledError]
        model.release.set()
        _wait_for(lambda: adapter._pending == 0)
        assert adapter.stats.late_results_discarded == 1

    def test_already_cancelled_call_never_loads_or_generates(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        loader = CountingLoader(FakeModel(good_reply(inputs)))
        adapter = build(adapters, loader)
        token = CancelToken()
        token.cancel()
        with pytest.raises(ProviderCancelledError):
            adapter.draft_outcome(DraftInputs(**{**inputs.__dict__, "cancel": token}))
        assert loader.calls == []

    def test_a_cancelled_queued_job_is_skipped_without_generating(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model), max_queue=1)
        first = threading.Thread(target=lambda: adapter.draft_outcome(inputs))
        first.start()
        assert model.entered.wait(timeout=10)
        token = CancelToken()
        queued_inputs = DraftInputs(**{**inputs.__dict__, "cancel": token})
        result: list[BaseException] = []

        def queued() -> None:
            try:
                adapter.draft_outcome(queued_inputs)
            except BaseException as error:
                result.append(error)

        second = threading.Thread(target=queued)
        second.start()
        _wait_for(lambda: adapter._pending == 2)
        token.cancel()
        second.join(timeout=5)
        model.release.set()
        first.join(timeout=15)
        _wait_for(lambda: adapter._pending == 0)
        assert [type(e) for e in result] == [ProviderCancelledError]
        assert model.generations == 1
        assert adapter.stats.skipped_before_start == 1

    def test_stream_fragments_stop_after_cancel(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs), fragments=30)
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model))
        token = CancelToken()
        seen: list[str] = []
        watched = DraftInputs(
            **{**inputs.__dict__, "cancel": token, "on_event": lambda e: seen.append(e.kind)}
        )
        thread = threading.Thread(target=lambda: _swallow(lambda: adapter.draft_outcome(watched)))
        thread.start()
        assert model.entered.wait(timeout=10)
        _wait_for(lambda: "delta" in seen)
        token.cancel()
        thread.join(timeout=5)
        count_at_cancel = seen.count("delta")
        model.release.set()
        _wait_for(lambda: adapter._pending == 0)
        assert seen.count("delta") == count_at_cancel
        assert "completed" not in seen


class TestEventLoopAndHealth:
    def test_blocking_generation_runs_off_the_event_loop(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model))

        async def scenario() -> tuple[int, str]:
            task = asyncio.create_task(adapter.adraft(inputs))
            ticks = 0
            while not model.entered.is_set():
                await asyncio.sleep(0.005)
            for _ in range(20):
                await asyncio.sleep(0.01)
                ticks += 1
            model.release.set()
            outcome = await task
            return ticks, outcome.draft.turn_id

        ticks, turn_id = asyncio.run(scenario())
        assert ticks == 20
        assert turn_id == TURN_ID

    def test_blocking_load_does_not_stall_the_event_loop(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        loader = CountingLoader(FakeModel(good_reply(inputs)))
        loader.gate = threading.Event()
        adapter = build(adapters, loader)

        async def scenario() -> int:
            task = asyncio.create_task(adapter.adraft(inputs))
            while not loader.entered.is_set():
                await asyncio.sleep(0.005)
            started = time.monotonic()
            await asyncio.sleep(0.05)
            elapsed = time.monotonic() - started
            loader.gate.set()  # type: ignore[union-attr]
            await task
            return int(elapsed * 1000)

        assert asyncio.run(scenario()) < 500

    def test_asyncio_cancellation_cancels_the_call_and_fences_the_result(
        self, inputs: DraftInputs, adapters: list[LocalTransformersAdapter]
    ) -> None:
        model = FakeModel(good_reply(inputs))
        model.honor_stop = False
        model.release = threading.Event()
        adapter = build(adapters, CountingLoader(model))
        token = CancelToken()
        watched = DraftInputs(**{**inputs.__dict__, "cancel": token})

        async def scenario() -> None:
            task = asyncio.create_task(adapter.adraft(watched))
            while not model.entered.is_set():
                await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        assert token.cancelled and token.reason == "asyncio-cancelled"
        model.release.set()
        _wait_for(lambda: adapter._pending == 0)

    def test_health_endpoints_answer_while_load_and_generation_are_blocked(
        self,
        inputs: DraftInputs,
        adapters: list[LocalTransformersAdapter],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        loader = CountingLoader(FakeModel(good_reply(inputs)))
        loader.gate = threading.Event()
        monkeypatch.setattr("app.inference.hf_transformers.load_transformers_model", loader)
        factory.reset_adapters()
        settings = Settings.model_validate(
            {
                "database_url": "sqlite://",
                "tutor_provider": "transformers",
                "tutor_local_model_load_enabled": True,
                "tutor_local_timeout_seconds": 10,
            }
        )
        adapter = factory.adapter_for(settings)
        client = TestClient(create_app(settings))
        thread = threading.Thread(target=lambda: _swallow(lambda: adapter.draft(inputs)))
        try:
            thread.start()
            assert loader.entered.wait(timeout=10)
            started = time.monotonic()
            assert client.get("/health").status_code == 200
            blocked = client.get("/health/model").json()
            assert time.monotonic() - started < 1.0
            assert blocked["state"] == "not_loaded" and blocked["ready"] is False

            loader.gate.set()
            thread.join(timeout=15)
            loaded = client.get("/health/model").json()
            assert loaded["state"] == "ready" and loaded["ready"] is True
            assert "loaded" in loaded["label"]
            assert loaded["transmission"] == "this_process"
        finally:
            loader.gate.set()
            thread.join(timeout=15)
            factory.reset_adapters()


class TestFactoryCaching:
    def test_adapter_for_returns_the_same_adapter_so_the_model_loads_once_per_process(
        self, monkeypatch: pytest.MonkeyPatch, inputs: DraftInputs
    ) -> None:
        loader = CountingLoader(FakeModel(good_reply(inputs)))
        monkeypatch.setattr("app.inference.hf_transformers.load_transformers_model", loader)
        factory.reset_adapters()
        settings = Settings.model_validate(
            {
                "database_url": "sqlite://",
                "tutor_provider": "transformers",
                "tutor_local_model_load_enabled": True,
            }
        )
        try:
            first = factory.adapter_for(settings)
            second = factory.adapter_for(settings)
            assert first is second
            first.draft(inputs)
            second.draft(inputs)
            assert len(loader.calls) == 1
            other = settings.model_copy(update={"tutor_local_model_revision": "other"})
            assert factory.adapter_for(other) is not first
        finally:
            factory.reset_adapters()


def _swallow(call: Callable[[], object]) -> None:
    with contextlib.suppress(Exception):
        call()


def _wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition was not reached"
        time.sleep(0.005)
