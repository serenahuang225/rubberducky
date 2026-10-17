"""Cooperative cancellation and deadlines shared by every adapter.

A timeout alone does not stop a running generation or HTTP read, so a :class:`CancelToken`
is the single place that says "this call no longer matters". Workers poll it between tokens
or stream events, and registered callbacks (for example closing an HTTP stream) run once on
cancel so a blocked read is released. Late results are separately fenced by the adapters:
nothing a cancelled call produces is ever returned.
"""

import contextlib
import threading
import time
from collections.abc import Callable

from app.inference.errors import ProviderCancelledError, ProviderTimeoutError


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []
        self.reason: str | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            if self._event.is_set():
                return
            self.reason = reason
            self._event.set()
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            # A failing release hook must not mask the cancel.
            with contextlib.suppress(Exception):
                callback()

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Run ``callback`` on cancel (immediately if already cancelled). Returns an unregister."""
        with self._lock:
            if not self._event.is_set():
                self._callbacks.append(callback)
                return lambda: self._unregister(callback)
        callback()
        return lambda: None

    def _unregister(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def wait(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; True if cancelled meanwhile."""
        return self._event.wait(max(0.0, seconds))

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise ProviderCancelledError(f"provider call cancelled ({self.reason})")


class Deadline:
    """A monotonic wall-clock budget for one provider call, including retries."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds
        self.seconds = seconds

    def remaining(self) -> float:
        return self._end - self._clock()

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0

    def raise_if_expired(self) -> None:
        if self.expired:
            raise ProviderTimeoutError(f"provider deadline of {self.seconds:g}s passed")
