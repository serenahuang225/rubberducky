"""Wait preference and "Still thinking": space for the learner, never evidence.

None of these routes creates an observation, hint, step, assessment or tutor turn, and none
changes the session revision or the board. Hint availability is computed from stored
activity and the server clock; asking for help is a separate route that does not wait.
"""

from fastapi import APIRouter

from app.api.deps import ScopedRepo
from app.api.errors import ApiError, ErrorEnvelope
from app.api.sessions import SessionIdPath
from app.clock import utc_now
from app.schemas.wait import WaitPreference, WaitPreferenceRequest, WaitState
from app.tutor import waiting

router = APIRouter(tags=["waiting"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
}


@router.get(
    "/me/wait-preference",
    response_model=WaitPreference,
    responses=_ERRORS,
    summary="How long to wait before an optional hint becomes available",
)
def get_wait_preference(repo: ScopedRepo) -> WaitPreference:
    return waiting.get_wait_preference(repo)


@router.put(
    "/me/wait-preference",
    response_model=WaitPreference,
    responses=_ERRORS,
    summary="Set the wait before an optional hint becomes available (own preference)",
)
def put_wait_preference(body: WaitPreferenceRequest, repo: ScopedRepo) -> WaitPreference:
    preference = waiting.put_wait_preference(repo, body.wait_seconds, utc_now())
    repo.db.commit()
    return preference


def _active_state(repo: ScopedRepo, session_id: str) -> WaitState:
    session = repo.require_session(session_id)
    if session.status != "active":
        raise ApiError(409, "session_not_active", "The session is not active.")
    return waiting.wait_state(repo, session_id, utc_now())


@router.get(
    "/sessions/{session_id}/wait",
    response_model=WaitState,
    responses=_ERRORS,
    summary="Thinking-time state: when an optional hint becomes available (no interruptions)",
)
def get_wait_state(session_id: SessionIdPath, repo: ScopedRepo) -> WaitState:
    return _active_state(repo, session_id)


@router.post(
    "/sessions/{session_id}/still-thinking",
    response_model=WaitState,
    responses=_ERRORS,
    summary="Still thinking: keep the space quiet for another wait period; creates no evidence",
)
def still_thinking(session_id: SessionIdPath, repo: ScopedRepo) -> WaitState:
    _active_state(repo, session_id)
    now = utc_now()
    waiting.record_still_thinking(repo, session_id, now)
    state = waiting.wait_state(repo, session_id, now)
    repo.db.commit()
    return state
