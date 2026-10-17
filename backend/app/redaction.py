"""One redaction path for logs, error envelopes and integration failures.

Secrets (provider keys, bearer tokens, pairing tokens) and raw media (inline base64 images or
audio) must never reach a log line, an error body or a stored failure. Everything that can
carry such text goes through :func:`redact_text` / :func:`redact_value`; the process-wide log
hook installed by :func:`install_log_redaction` applies the same functions to every record.

Redaction is a safety net, not a licence to log values: callers still avoid putting secrets
or media into messages in the first place.
"""

import logging
import re
import threading
import traceback
from collections.abc import Iterable
from typing import Any

REDACTED = "[redacted]"
REDACTED_MEDIA = "[redacted media]"

_MIN_SECRET_LENGTH = 6
_MAX_FIELD_MESSAGE_CHARS = 200

_SENSITIVE_KEY = re.compile(
    r"authorization|api[_-]?key|secret|passw(or)?d|credential|cookie|^token$|_token$|"
    r"access[_-]?token|base64|raw[_-]?(media|audio|image|video)|^audio$|^image$|^frame$",
    re.IGNORECASE,
)
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"data:[A-Za-z0-9.+/-]+;base64,[A-Za-z0-9+/=_-]+"), REDACTED_MEDIA),
    # A word like "credential" after "bearer" is prose: require a digit or a long run.
    (
        re.compile(
            r"(?i)\bBearer\s+(?:(?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{8,}"
            r"|[A-Za-z0-9._~+/=-]{24,})"
        ),
        f"Bearer {REDACTED}",
    ),
    (re.compile(r"\brdk_[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
    (
        re.compile(
            r"(?i)\b((?:api[_-]?key|access[_-]?token|token|secret|password|authorization)"
            r"[\"']?\s*[=:]\s*[\"']?)[^\s\"',;&}]{4,}"
        ),
        rf"\1{REDACTED}",
    ),
    (re.compile(r"[A-Za-z0-9+/]{200,}={0,2}"), REDACTED_MEDIA),
)

_lock = threading.Lock()
_known_secrets: set[str] = set()


def register_secrets(values: Iterable[str | None]) -> None:
    """Remember exact secret values so they are removed wherever they appear."""
    with _lock:
        for value in values:
            if value is not None and len(value) >= _MIN_SECRET_LENGTH:
                _known_secrets.add(value)


def redact_text(text: str) -> str:
    redacted = text
    with _lock:
        known = sorted(_known_secrets, key=len, reverse=True)
    for secret in known:
        redacted = redacted.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact strings, and drop the value under any sensitive-looking key."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: REDACTED
            if isinstance(key, str) and _SENSITIVE_KEY.search(key)
            else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, bytes | bytearray):
        return REDACTED_MEDIA
    return value


def safe_field_message(message: str) -> str:
    """A validation message that keeps its diagnostic wording but not echoed input."""
    return redact_text(message)[:_MAX_FIELD_MESSAGE_CHARS]


_factory_lock = threading.Lock()
_installed = False


def install_log_redaction() -> None:
    """Redact every log record (message, arguments and exception text) at creation time."""
    global _installed
    with _factory_lock:
        if _installed:
            return
        previous = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous(*args, **kwargs)
            try:
                message = record.getMessage()
            except (TypeError, ValueError):
                message = str(record.msg)
            record.msg = redact_text(message)
            record.args = ()
            if record.exc_info and record.exc_info[0] is not None:
                text = "".join(traceback.format_exception(*record.exc_info))
                record.exc_text = redact_text(text)
                # The live exception object still holds the raw message; only text survives.
                record.exc_info = None
            return record

        logging.setLogRecordFactory(factory)
        _installed = True
