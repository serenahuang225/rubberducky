"""Local, rotating activity log. Records metadata only, never request/response bodies."""

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.redaction import redact_value

_current: ContextVar[tuple["ActivityLog", str] | None] = ContextVar("activity", default=None)


class ActivityLog:
    def __init__(self, path: str) -> None:
        self.path = path
        self._handler: RotatingFileHandler | None = None
        self._lock = threading.Lock()

    def write(self, event: str, request_id: str, **fields: Any) -> None:
        try:
            with self._lock:
                if self._handler is None:
                    Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                    self._handler = RotatingFileHandler(
                        self.path,
                        maxBytes=5_000_000,
                        backupCount=3,
                        encoding="utf-8",
                        delay=True,
                    )
                entry = redact_value(
                    {
                        "time": datetime.now(UTC).isoformat(),
                        "event": event,
                        "request_id": request_id,
                        **fields,
                    }
                )
                record = logging.LogRecord(
                    "activity", logging.INFO, "", 0, json.dumps(entry), (), None
                )
                self._handler.handle(record)
        except (OSError, ValueError):
            # Observability must never make a request fail.
            logging.getLogger(__name__).warning("Activity log could not be written")

    def close(self) -> None:
        with self._lock:
            if self._handler is not None:
                self._handler.close()
                self._handler = None


def activity(event: str, **fields: Any) -> None:
    current = _current.get()
    if current is not None:
        log, request_id = current
        log.write(event, request_id, **fields)


class ActivityMiddleware:
    def __init__(self, app: ASGIApp, log: ActivityLog) -> None:
        self.app = app
        self.log = log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        token = _current.set((self.log, request_id))
        started = time.monotonic()
        status = 500

        async def observed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        activity("http.started", method=scope["method"])
        try:
            await self.app(scope, receive, observed_send)
        except BaseException as error:
            activity("http.failed", error_type=type(error).__name__)
            raise
        finally:
            # Use the route template: URLs and query strings may contain secrets.
            route = scope.get("route")
            activity(
                "http.completed",
                method=scope["method"],
                route=getattr(route, "path", "<unmatched>"),
                status=status,
                duration_ms=round((time.monotonic() - started) * 1000, 1),
            )
            _current.reset(token)
