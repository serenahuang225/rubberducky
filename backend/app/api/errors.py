"""Uniform JSON error envelope: ``{"schema_version": "error.v1", "error": {code, message}}``."""

import math
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.db.repositories import NotInScopeError


class ErrorDetail(BaseModel):
    code: str
    message: str


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


def _envelope(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


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


def _json_safe(value: Any) -> Any:
    """Replace non-finite floats so a rejected NaN/inf input never breaks the 422 body."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


async def _request_validation(_request: Request, exc: Exception) -> JSONResponse:
    # Same {"detail": [...]} shape as FastAPI's default 422, sanitized for JSON compliance.
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered for it only
    return JSONResponse(
        status_code=422, content=jsonable_encoder({"detail": _json_safe(exc.errors())})
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(NotInScopeError, _not_in_scope)
    app.add_exception_handler(OperationalError, _database_unavailable)
    app.add_exception_handler(RequestValidationError, _request_validation)
