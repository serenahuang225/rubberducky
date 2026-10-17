"""Uniform JSON error envelope: ``{"schema_version": "error.v1", "error": {code, message}}``."""

from typing import Literal

from fastapi import FastAPI, Request
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


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(NotInScopeError, _not_in_scope)
    app.add_exception_handler(OperationalError, _database_unavailable)
