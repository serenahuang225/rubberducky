"""Uniform JSON error envelope: ``{"schema_version": "error.v1", "error": {code, message}}``.

Every body is built by :func:`error_body`, which runs the shared redaction first, so a
provider failure, a rejected media event or a synthetic integration error cannot echo a
secret or raw media. Request-validation failures (422) use the same envelope with
``error.fields`` carrying safe per-field diagnostics (location, stable type, short message);
the submitted input itself is never echoed.
"""

from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.db.repositories import NotInScopeError
from app.redaction import redact_text, safe_field_message

_MAX_FIELD_ISSUES = 20
_MAX_LOC_PART_CHARS = 64


class FieldIssue(BaseModel):
    loc: list[str | int]
    type: str
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[FieldIssue] | None = None


class ErrorEnvelope(BaseModel):
    schema_version: Literal["error.v1"] = "error.v1"
    error: ErrorDetail


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def error_body(code: str, message: str, fields: list[FieldIssue] | None = None) -> dict[str, Any]:
    """The documented envelope as a dict, redacted. Also used for integration failures."""
    envelope = ErrorEnvelope(
        error=ErrorDetail(code=redact_text(code)[:64], message=redact_text(message), fields=fields)
    )
    return envelope.model_dump(exclude_none=True)


def _envelope(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message), headers=headers)


def unauthenticated() -> ApiError:
    return ApiError(
        401,
        "unauthenticated",
        "A valid paired bearer credential is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def not_found() -> ApiError:
    # Same response whether the record is missing or belongs to another learner.
    return ApiError(404, "not_found", "No such record for this learner.")


async def _api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101 - registered for ApiError only
    return _envelope(exc.status_code, exc.code, exc.message, exc.headers)


async def _not_in_scope(_request: Request, _exc: Exception) -> JSONResponse:
    error = not_found()
    return _envelope(error.status_code, error.code, error.message)


async def _database_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    # SQL text is deliberately not echoed; it can contain record values.
    return _envelope(
        503,
        "database_unavailable",
        "The database is unavailable or not migrated. Run `python -m app.cli migrate`.",
    )


def _loc_part(part: Any) -> str | int:
    if isinstance(part, int):
        return part
    return redact_text(str(part))[:_MAX_LOC_PART_CHARS]


def field_issues(errors: list[Any]) -> list[FieldIssue]:
    """Safe diagnostics from pydantic errors: never ``input`` or ``ctx`` (they echo values)."""
    issues: list[FieldIssue] = []
    for item in errors[:_MAX_FIELD_ISSUES]:
        issues.append(
            FieldIssue(
                loc=[_loc_part(part) for part in item.get("loc", ())],
                type=str(item.get("type", "invalid"))[:48],
                message=safe_field_message(str(item.get("msg", "Invalid value"))),
            )
        )
    return issues


async def _request_validation(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered for it only
    content = error_body(
        "validation_error",
        "The request was not valid. See error.fields for what to fix; the submitted values "
        "are not echoed.",
        field_issues(list(exc.errors())),
    )
    return JSONResponse(status_code=422, content=content)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(NotInScopeError, _not_in_scope)
    app.add_exception_handler(OperationalError, _database_unavailable)
    app.add_exception_handler(RequestValidationError, _request_validation)
