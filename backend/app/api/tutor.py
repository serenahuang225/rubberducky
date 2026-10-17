"""Core tutor routes: persona choice, session state, check-ins, work and turn events.

Every route is learner-scoped through the paired bearer credential. Turn commands require an
``Idempotency-Key`` header and the expected session revision; identical retries replay the
stored outcome, conflicting revisions or reused keys are rejected, and the deterministic
mock provider runs on the same coordinator path any other provider would.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import ScopeDep, ScopedRepo, SettingsDep, get_database
from app.api.errors import ApiError, ErrorEnvelope
from app.api.sessions import SessionIdPath
from app.clock import utc_now
from app.config import Settings
from app.db.database import Database
from app.inference.providers import ProviderUnavailableError
from app.learner.pairing import LearnerScope
from app.schemas import TutorConfiguration
from app.schemas.tutor import (
    CheckInRequest,
    HelpRequest,
    PersonaOptions,
    SessionState,
    TutorConfigurationRequest,
    TutorTurnResult,
    WorkRequest,
)
from app.tutor import state as tutor_state
from app.tutor.coordinator import TurnCommandError, execute_turn

router = APIRouter(tags=["tutor"])

DatabaseDep = Annotated[Database, Depends(get_database)]
IdempotencyKeyHeader = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


def _run_turn(
    database: Database,
    scope: LearnerScope,
    settings: Settings,
    session_id: str,
    kind: str,
    body: CheckInRequest | WorkRequest | HelpRequest,
    idempotency_key: str,
) -> TutorTurnResult:
    try:
        return execute_turn(
            database, scope, settings, session_id, kind, body, idempotency_key, utc_now()
        )
    except TurnCommandError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except ProviderUnavailableError as error:
        raise ApiError(503, "provider_unavailable", str(error)) from error


@router.get(
    "/persona/options",
    response_model=PersonaOptions,
    responses=_ERRORS,
    summary="The independently selectable persona axes (appearances, personalities, comfort)",
)
def get_persona_options(_repo: ScopedRepo) -> PersonaOptions:
    return tutor_state.persona_options()


@router.put(
    "/me/tutor-configuration",
    response_model=TutorConfiguration,
    responses=_ERRORS,
    summary="Choose or change the persona; appearance and personality are independent",
)
def put_tutor_configuration(
    body: TutorConfigurationRequest, repo: ScopedRepo
) -> TutorConfiguration:
    config = tutor_state.configure_persona(repo, body, utc_now())
    repo.db.commit()
    return config


@router.get(
    "/sessions/{session_id}/state",
    response_model=SessionState,
    responses=_ERRORS,
    summary="Resumable session state: current problem, revision, pace and persona",
)
def get_session_state(session_id: SessionIdPath, repo: ScopedRepo) -> SessionState:
    return tutor_state.session_state(repo, session_id, utc_now())


@router.post(
    "/sessions/{session_id}/check-in",
    response_model=TutorTurnResult,
    responses=_ERRORS,
    summary="Record a self-report check-in, set the goal and pose the current problem",
)
def check_in(
    session_id: SessionIdPath,
    body: CheckInRequest,
    idempotency_key: IdempotencyKeyHeader,
    scope: ScopeDep,
    database: DatabaseDep,
    settings: SettingsDep,
) -> TutorTurnResult:
    return _run_turn(database, scope, settings, session_id, "check_in", body, idempotency_key)


@router.post(
    "/sessions/{session_id}/work",
    response_model=TutorTurnResult,
    responses=_ERRORS,
    summary="Submit a typed or confirmed step, answer or explanation for the current problem",
)
def submit_work(
    session_id: SessionIdPath,
    body: WorkRequest,
    idempotency_key: IdempotencyKeyHeader,
    scope: ScopeDep,
    database: DatabaseDep,
    settings: SettingsDep,
) -> TutorTurnResult:
    return _run_turn(database, scope, settings, session_id, "work", body, idempotency_key)


@router.post(
    "/sessions/{session_id}/help",
    response_model=TutorTurnResult,
    responses=_ERRORS,
    summary="Help me: a hint (or an explanation when asked) now, without waiting for any timer",
)
def ask_for_help(
    session_id: SessionIdPath,
    body: HelpRequest,
    idempotency_key: IdempotencyKeyHeader,
    scope: ScopeDep,
    database: DatabaseDep,
    settings: SettingsDep,
) -> TutorTurnResult:
    return _run_turn(database, scope, settings, session_id, "help", body, idempotency_key)


@router.get(
    "/sessions/{session_id}/events",
    response_model=list[TutorTurnResult],
    responses=_ERRORS,
    summary="Chronological tutor turn outcomes for this session (poll to stream updates)",
)
def get_turn_events(
    session_id: SessionIdPath,
    repo: ScopedRepo,
    limit: Annotated[int, Query(ge=1, le=tutor_state.MAX_TURN_EVENTS)] = 20,
) -> list[TutorTurnResult]:
    return tutor_state.list_turn_events(repo, session_id, limit)


@router.get(
    "/sessions/{session_id}/turns/{turn_id}",
    response_model=TutorTurnResult,
    responses=_ERRORS,
    summary="One tutor turn outcome, including validation rejections",
)
def get_turn(
    session_id: SessionIdPath, turn_id: SessionIdPath, repo: ScopedRepo
) -> TutorTurnResult:
    return tutor_state.get_turn_result(repo, session_id, turn_id)
