"""Learner-scoped tutoring session lifecycle."""

from typing import Annotated

from fastapi import APIRouter, Path, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import ScopedRepo
from app.api.errors import ErrorEnvelope
from app.clock import utc_now
from app.learner.removal import delete_session as remove_session
from app.schemas import Session
from app.schemas.agency import RemovalReceipt

router = APIRouter(prefix="/sessions", tags=["sessions"])

SessionIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
}


class StartSessionRequest(BaseModel):
    # Unknown fields such as a client-supplied learner_id are rejected, never trusted.
    model_config = ConfigDict(extra="forbid")

    goal: Annotated[str, Field(min_length=1, max_length=200)] | None = None


@router.post(
    "",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Start a session for the paired learner",
)
def start_session(body: StartSessionRequest, repo: ScopedRepo) -> Session:
    session = repo.start_session(body.goal, utc_now())
    repo.db.commit()
    return session


@router.get("", response_model=list[Session], responses=_ERRORS, summary="Recent own sessions")
def list_sessions(repo: ScopedRepo) -> list[Session]:
    return repo.list_sessions()


@router.get("/{session_id}", response_model=Session, responses=_ERRORS, summary="One own session")
def get_session(session_id: SessionIdPath, repo: ScopedRepo) -> Session:
    return repo.get_session(session_id)


@router.post(
    "/{session_id}/end", response_model=Session, responses=_ERRORS, summary="End an own session"
)
def end_session(session_id: SessionIdPath, repo: ScopedRepo) -> Session:
    session = repo.end_session(session_id, utc_now())
    repo.db.commit()
    return session


@router.delete(
    "/{session_id}",
    response_model=RemovalReceipt,
    responses=_ERRORS,
    summary="Delete an own session and everything recorded in it; dependents recompute",
)
def delete_session(session_id: SessionIdPath, repo: ScopedRepo) -> RemovalReceipt:
    receipt = remove_session(repo, session_id, utc_now())
    repo.db.commit()
    return receipt
