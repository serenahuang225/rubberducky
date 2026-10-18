"""Shared machinery for remote providers (Claude, OpenAI-compatible endpoint).

One draft is at most ``max_attempts`` transport calls inside one overall :class:`Deadline`.
Only :class:`TransientProviderError` is repeated, with exponential backoff that honors a
provider's ``Retry-After`` but never sleeps past the deadline. A malformed, stale or
truncated answer is *not* retried: the learner's turn fails with a typed error instead of a
second paid call that might drift from the plan. Nothing falls back to another provider.

The transport (``_complete``) returns only a finished completion; fragments seen while it
streams are reported as ``delta`` events and are never shown or committed.
"""

import threading
from dataclasses import dataclass

from app.activity import activity
from app.config import Settings
from app.inference.adapter import DraftAdapter
from app.inference.cancel import CancelToken, Deadline
from app.inference.errors import (
    ProviderBusyError,
    ProviderError,
    ProviderTimeoutError,
    RequestTooLargeError,
    RetriesExhaustedError,
    TransientProviderError,
    TruncatedDraftError,
)
from app.inference.events import (
    DraftOutcome,
    EventRecorder,
    parse_final_draft,
    with_contract,
)
from app.inference.providers import DraftInputs
from app.inference.request import ProviderMessage

MAX_BACKOFF_SECONDS = 30.0
MAX_CONCURRENT_CALLS = 4


@dataclass(frozen=True)
class RemoteLimits:
    timeout_seconds: float
    max_attempts: int
    backoff_seconds: float
    max_output_tokens: int
    max_request_chars: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "RemoteLimits":
        return cls(
            timeout_seconds=settings.tutor_remote_timeout_seconds,
            max_attempts=settings.tutor_remote_max_attempts,
            backoff_seconds=settings.tutor_remote_backoff_seconds,
            max_output_tokens=settings.tutor_remote_max_output_tokens,
            max_request_chars=settings.tutor_remote_max_request_chars,
        )


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    hit_length_limit: bool


@dataclass
class CallContext:
    """Per-attempt handles a transport needs; ``recorder`` carries stream fragments out."""

    messages: list[ProviderMessage]
    max_output_tokens: int
    cancel: CancelToken
    deadline: Deadline
    recorder: EventRecorder


class RemoteAdapter(DraftAdapter):
    def __init__(self, limits: RemoteLimits) -> None:
        self.limits = limits
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_CALLS)
        self._counter_lock = threading.Lock()
        self.calls_made = 0

    def _complete(self, call: CallContext) -> Completion:
        raise NotImplementedError

    def draft_outcome(self, inputs: DraftInputs) -> DraftOutcome:
        cancel = inputs.cancel
        cancel.raise_if_cancelled()
        request = inputs.request
        if request.request_chars > self.limits.max_request_chars:
            raise RequestTooLargeError(
                f"request of {request.request_chars} characters exceeds the configured "
                f"{self.limits.max_request_chars}-character ceiling"
            )
        if not self._slots.acquire(blocking=False):
            raise ProviderBusyError(f"{MAX_CONCURRENT_CALLS} remote calls are already in flight")
        try:
            return self._attempts(inputs)
        finally:
            self._slots.release()

    def _attempts(self, inputs: DraftInputs) -> DraftOutcome:
        recorder = EventRecorder(inputs.on_event)
        deadline = Deadline(self.limits.timeout_seconds)
        call = CallContext(
            messages=with_contract(inputs.request.messages, inputs.plan, inputs.session_revision),
            max_output_tokens=min(inputs.request.max_output_tokens, self.limits.max_output_tokens),
            cancel=inputs.cancel,
            deadline=deadline,
            recorder=recorder,
        )
        last: TransientProviderError | None = None
        for attempt in range(1, self.limits.max_attempts + 1):
            inputs.cancel.raise_if_cancelled()
            deadline.raise_if_expired()
            try:
                activity(
                    "provider.request",
                    provider=self.name,
                    model=getattr(self, "model", None),
                    attempt=attempt,
                    request_chars=sum(len(m.content) for m in call.messages),
                    max_output_tokens=call.max_output_tokens,
                )
                recorder.emit("started", attempt=attempt)
                with self._counter_lock:
                    self.calls_made += 1
                completion = self._complete(call)
            except TransientProviderError as error:
                last = error
                recorder.emit("retry", attempt=attempt, code=error.code)
                if attempt == self.limits.max_attempts:
                    break
                self._backoff(attempt, error, call)
                continue
            except ProviderError as error:
                recorder.emit("failed", attempt=attempt, code=error.code)
                raise
            activity(
                "provider.response",
                provider=self.name,
                attempt=attempt,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                response_chars=len(completion.text),
            )
            # Fence: a result that finished after a cancel or deadline is never returned.
            inputs.cancel.raise_if_cancelled()
            deadline.raise_if_expired()
            try:
                if completion.hit_length_limit:
                    raise TruncatedDraftError("provider stopped at the output-token limit")
                draft = parse_final_draft(
                    completion.text,
                    turn_id=inputs.plan.turn_id,
                    session_revision=inputs.session_revision,
                )
            except ProviderError as error:
                recorder.emit("failed", attempt=attempt, code=error.code)
                raise
            recorder.emit("completed", attempt=attempt)
            return DraftOutcome(
                draft=draft,
                events=tuple(recorder.events),
                attempts=attempt,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
            )
        exhausted = RetriesExhaustedError(
            self.limits.max_attempts, last or TransientProviderError()
        )
        recorder.emit("failed", attempt=self.limits.max_attempts, code=exhausted.code)
        raise exhausted

    def _backoff(self, attempt: int, error: TransientProviderError, call: CallContext) -> None:
        delay = self.limits.backoff_seconds * (2 ** (attempt - 1))
        if error.retry_after is not None:
            delay = max(delay, error.retry_after)
        delay = min(delay, MAX_BACKOFF_SECONDS)
        if delay >= call.deadline.remaining():
            raise ProviderTimeoutError("the deadline leaves no time for another attempt")
        if call.cancel.wait(delay):
            call.cancel.raise_if_cancelled()
