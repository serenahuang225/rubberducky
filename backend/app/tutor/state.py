"""Learner-scoped read models: resumable session state, turn events and persona choice."""

from datetime import datetime

from sqlalchemy import select

from app.db.models import TutorTurnRow
from app.db.repositories import NotInScopeError, ScopedRepository
from app.learner.memory import active_session_context, stale_session_context_count
from app.pedagogy.persona import APPEARANCES, COMFORT_OVERRIDES, PERSONALITIES
from app.pedagogy.problems import UnknownProblemError
from app.schemas import Session
from app.schemas.tutor import (
    PersonaOptions,
    SessionState,
    TutorTurnResult,
)
from app.tutor.brought_question import spec_for_stored_problem
from app.tutor.evidence import open_attempt, problem_view, statement_object_id

MAX_TURN_EVENTS = 50


def persona_options() -> PersonaOptions:
    """The independently selectable first-run persona axes (3 appearances x 5 ducks)."""
    return PersonaOptions(
        appearances=list(APPEARANCES),
        personalities=list(PERSONALITIES),
        comfort_overrides=list(COMFORT_OVERRIDES),
    )


def session_state(repo: ScopedRepository, session_id: str, now: datetime) -> SessionState:
    """The resumable view: current problem, revision (via the session), pace and persona."""
    session = Session.model_validate(repo.require_session(session_id))
    current = None
    attempt = open_attempt(repo, session_id)
    if attempt is not None:
        try:
            spec = spec_for_stored_problem(repo, attempt.problem_id)
        except UnknownProblemError:
            spec = None
        if spec is not None:
            current = problem_view(
                spec, attempt.id, statement_object_id(session_id, spec.problem_id)
            )
    latest = repo.db.execute(
        select(TutorTurnRow)
        .where(
            TutorTurnRow.learner_id == repo.learner_id,
            TutorTurnRow.session_id == session_id,
            TutorTurnRow.status == "committed",
        )
        .order_by(TutorTurnRow.created_at.desc(), TutorTurnRow.id)
        .limit(1)
    ).scalar_one_or_none()
    pending = repo.db.execute(
        select(TutorTurnRow.id)
        .where(
            TutorTurnRow.learner_id == repo.learner_id,
            TutorTurnRow.session_id == session_id,
            TutorTurnRow.status == "pending",
        )
        .order_by(TutorTurnRow.created_at.desc(), TutorTurnRow.id)
        .limit(1)
    ).scalar_one_or_none()
    recheck = stale_session_context_count(repo, session_id, now) > 0 and not active_session_context(
        repo, session_id, now
    )
    return SessionState(
        session=session,
        current_problem=current,
        pace="standard" if latest is None else latest.result.get("pace", "standard"),
        pending_turn_id=pending,
        session_context_recheck=recheck,
        persona=repo.tutor_configuration(),
    )


def list_turn_events(
    repo: ScopedRepository, session_id: str, limit: int = MAX_TURN_EVENTS
) -> list[TutorTurnResult]:
    """Chronological turn outcomes for one own session (the documented event log to poll)."""
    repo.require_session(session_id)
    bounded = max(1, min(limit, MAX_TURN_EVENTS))
    rows = list(
        repo.db.execute(
            select(TutorTurnRow)
            .where(
                TutorTurnRow.learner_id == repo.learner_id,
                TutorTurnRow.session_id == session_id,
            )
            .order_by(TutorTurnRow.created_at.desc(), TutorTurnRow.id)
            .limit(bounded)
        ).scalars()
    )
    return [TutorTurnResult.model_validate(row.result) for row in reversed(rows)]


def get_turn_result(repo: ScopedRepository, session_id: str, turn_id: str) -> TutorTurnResult:
    repo.require_session(session_id)
    row = repo.db.execute(
        select(TutorTurnRow).where(
            TutorTurnRow.id == turn_id,
            TutorTurnRow.learner_id == repo.learner_id,
            TutorTurnRow.session_id == session_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotInScopeError("tutor_turns")
    return TutorTurnResult.model_validate(row.result)
