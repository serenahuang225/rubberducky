"""Local model adapter: lazy, bounded, cancellable, and honest about what ran.

Nothing here imports a model library or touches the network. A :data:`LocalModelLoader`
(``app.inference.hf_transformers.load_transformers_model`` in production) is called at most
once per process, on the first generation, under a lock. Loading and generation are blocking,
so they run on one dedicated worker thread: generations are serialized, at most
``max_queue`` more may wait, and anything beyond that is refused at once.

A timeout or cancel does not rely on the worker noticing. The worker polls a stop signal
between tokens, and the result is additionally *fenced*: the caller takes the result under
a lock or fences the job, so output produced after a cancel or deadline is discarded and can
never be committed.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.config import Settings
from app.inference.adapter import DraftAdapter
from app.inference.cancel import CancelToken, Deadline
from app.inference.errors import (
    ModelLoadError,
    ProviderBusyError,
    ProviderCancelledError,
    ProviderError,
    ProviderTimeoutError,
    RequestTooLargeError,
    TruncatedDraftError,
)
from app.inference.events import (
    AdapterCapabilities,
    DraftOutcome,
    EventRecorder,
    parse_final_draft,
    with_contract,
)
from app.inference.providers import DraftInputs
from app.inference.request import ProviderMessage
from app.schemas.tutor import ProviderLabel

LoadState = Literal["not_loaded", "loaded", "failed"]


@dataclass(frozen=True)
class LocalModelConfig:
    model_id: str
    revision: str
    device: str
    dtype: str
    allow_download: bool
    context_window_tokens: int
    max_new_tokens: int
    max_queue: int
    timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "LocalModelConfig":
        return cls(
            model_id=settings.tutor_local_model_id,
            revision=settings.tutor_local_model_revision,
            device=settings.tutor_local_device,
            dtype=settings.tutor_local_dtype,
            allow_download=settings.tutor_local_allow_download,
            context_window_tokens=settings.tutor_local_context_window_tokens,
            max_new_tokens=settings.tutor_local_max_new_tokens,
            max_queue=settings.tutor_local_max_queue,
            timeout_seconds=settings.tutor_local_timeout_seconds,
        )


@dataclass(frozen=True)
class GenerationOutput:
    text: str
    output_tokens: int
    # True when generation stopped at the new-token ceiling instead of an end-of-sequence.
    hit_length_limit: bool


class LocalModel(Protocol):
    def count_prompt_tokens(self, messages: list[ProviderMessage]) -> int:
        """Exact prompt length after the model's own chat template."""
        ...

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        max_new_tokens: int,
        should_stop: Callable[[], bool],
        on_text: Callable[[str], None],
    ) -> GenerationOutput: ...


LocalModelLoader = Callable[[LocalModelConfig], LocalModel]


@dataclass
class _Job:
    inputs: DraftInputs
    messages: list[ProviderMessage]
    max_new_tokens: int
    cancel: CancelToken
    deadline: Deadline
    recorder: EventRecorder
    done: threading.Event
    lock: threading.Lock = field(default_factory=threading.Lock)
    fenced: bool = False
    finished: bool = False
    outcome: DraftOutcome | None = None
    error: ProviderError | None = None

    def should_stop(self) -> bool:
        return self.fenced or self.cancel.cancelled or self.deadline.expired

    def deliver(self, outcome: DraftOutcome | None, error: ProviderError | None) -> bool:
        with self.lock:
            if self.fenced:
                return False
            self.finished = True
            self.outcome, self.error = outcome, error
        return True


@dataclass
class LocalStats:
    loads: int = 0
    generations_started: int = 0
    late_results_discarded: int = 0
    skipped_before_start: int = 0
    refused_busy: int = 0


class LocalTransformersAdapter(DraftAdapter):
    name = "transformers"

    def __init__(self, config: LocalModelConfig, loader: LocalModelLoader) -> None:
        self.config = config
        self.stats = LocalStats()
        self._loader = loader
        self._model: LocalModel | None = None
        self._load_failure: str | None = None
        self._load_lock = threading.Lock()
        self._admission = threading.Lock()
        self._pending = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-model")

    # -- identity and state --------------------------------------------------------------

    def label(self) -> ProviderLabel:
        model = self.config.model_id[:52]
        return ProviderLabel(
            name=self.name,
            is_mock=False,
            label=f"Local model {model} on {self.config.device} (runs on this machine)"[:120],
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            streaming=True, cancellable=True, retries=False, transmission="this_process"
        )

    @property
    def load_state(self) -> LoadState:
        if self._model is not None:
            return "loaded"
        return "failed" if self._load_failure else "not_loaded"

    @property
    def last_load_failure(self) -> str | None:
        return self._load_failure

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- the call ------------------------------------------------------------------------

    def draft_outcome(self, inputs: DraftInputs) -> DraftOutcome:
        cancel = inputs.cancel
        cancel.raise_if_cancelled()
        request = inputs.request
        max_new = min(request.max_output_tokens, self.config.max_new_tokens)
        messages = with_contract(request.messages, inputs.plan, inputs.session_revision)
        recorder = EventRecorder(inputs.on_event)
        job = _Job(
            inputs=inputs,
            messages=messages,
            max_new_tokens=max_new,
            cancel=cancel,
            deadline=Deadline(self.config.timeout_seconds),
            recorder=recorder,
            done=threading.Event(),
        )
        with self._admission:
            if self._pending >= 1 + self.config.max_queue:
                self.stats.refused_busy += 1
                raise ProviderBusyError(
                    f"{self._pending} local generations already running or queued"
                )
            self._pending += 1
        try:
            self._executor.submit(self._run_job, job)
        except RuntimeError:
            with self._admission:
                self._pending -= 1
            raise ProviderCancelledError("local adapter is closed") from None

        unregister = cancel.on_cancel(job.done.set)
        try:
            job.done.wait(timeout=max(0.0, job.deadline.remaining()))
        finally:
            unregister()
        with job.lock:
            if job.finished:
                outcome, error = job.outcome, job.error
            else:
                job.fenced = True
                outcome, error = None, None
        if error is not None:
            raise error
        if outcome is not None:
            return outcome
        if cancel.cancelled:
            raise ProviderCancelledError(f"local generation cancelled ({cancel.reason})")
        raise ProviderTimeoutError(
            f"local generation passed its {self.config.timeout_seconds:g}s deadline"
        )

    # -- worker thread -------------------------------------------------------------------

    def _run_job(self, job: _Job) -> None:
        try:
            if job.should_stop():
                self.stats.skipped_before_start += 1
                return
            outcome, error = self._generate(job)
            if not job.deliver(outcome, error):
                self.stats.late_results_discarded += 1
        except Exception as unexpected:  # worker must never die silently
            wrapped = ProviderError(f"local worker failed ({type(unexpected).__name__})")
            if not job.deliver(None, wrapped):
                self.stats.late_results_discarded += 1
        finally:
            with self._admission:
                self._pending -= 1
            job.done.set()

    def _generate(self, job: _Job) -> tuple[DraftOutcome | None, ProviderError | None]:
        try:
            model = self._ensure_loaded()
            if job.should_stop():
                return None, None
            prompt_tokens = model.count_prompt_tokens(job.messages)
            if prompt_tokens + job.max_new_tokens > self.config.context_window_tokens:
                raise RequestTooLargeError(
                    f"prompt of {prompt_tokens} tokens plus {job.max_new_tokens} new tokens "
                    f"exceeds the {self.config.context_window_tokens}-token window"
                )
            self.stats.generations_started += 1
            job.recorder.emit("started")

            def on_text(fragment: str) -> None:
                if not job.should_stop():
                    job.recorder.emit("delta", text=fragment)

            output = model.generate(
                job.messages,
                max_new_tokens=job.max_new_tokens,
                should_stop=job.should_stop,
                on_text=on_text,
            )
            if job.should_stop():
                return None, None
            if output.hit_length_limit:
                raise TruncatedDraftError("local generation stopped at the new-token limit")
            draft = parse_final_draft(
                output.text,
                turn_id=job.inputs.plan.turn_id,
                session_revision=job.inputs.session_revision,
            )
            job.recorder.emit("completed")
            return (
                DraftOutcome(
                    draft=draft,
                    events=tuple(job.recorder.events),
                    attempts=1,
                    input_tokens=prompt_tokens,
                    output_tokens=output.output_tokens,
                ),
                None,
            )
        except ProviderError as error:
            job.recorder.emit("failed", code=error.code)
            return None, error

    def _ensure_loaded(self) -> LocalModel:
        with self._load_lock:
            if self._model is not None:
                return self._model
            started = time.monotonic()
            try:
                model = self._loader(self.config)
            except ProviderError as error:
                self._load_failure = error.code
                raise
            except Exception as error:
                self._load_failure = ModelLoadError.code
                raise ModelLoadError(
                    f"local model load failed ({type(error).__name__}); weights are loaded "
                    "from the local cache only unless TUTOR_LOCAL_ALLOW_DOWNLOAD=true"
                ) from None
            self.stats.loads += 1
            self._load_failure = None
            self._model = model
            self.load_seconds = time.monotonic() - started
            return model

    load_seconds: float | None = None
