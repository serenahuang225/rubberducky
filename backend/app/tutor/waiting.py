"""Wait preference, "Still thinking" and the silence-safe hint availability clock.

Everything is derived from stored activity and an explicit ``now``, so a controlled clock can
advance any idle period. No function here creates an observation, hint, step, assessment or
turn: silence is missing evidence. Elapsed time only decides when an optional hint is
available to ask for; Help me never waits for it.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.db.models import (
    PreferenceRow,
    SceneOperationRow,
    SessionWaitSignalRow,
    StepRow,
    TutorTurnRow,
)
from app.db.repositories import ScopedRepository
from app.learner.memory import set_preference
from app.pedagogy.scaffolds import next_level
from app.schemas.wait import (
    DEFAULT_WAIT_SECONDS,
    WaitPreference,
    WaitState,
)
from app.tutor.evidence import attempt_hints, open_attempt

WAIT_PREFERENCE_KEY = "wait_seconds"


def get_wait_preference(repo: ScopedRepository) -> WaitPreference:
    row = repo.db.execute(
        select(PreferenceRow).where(
            PreferenceRow.learner_id == repo.learner_id, PreferenceRow.key == WAIT_PREFERENCE_KEY
        )
    ).scalar_one_or_none()
    if row is not None:
        value = row.value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return WaitPreference(
                wait_seconds=value, source="preference", updated_at=row.updated_at
            )
    return WaitPreference(wait_seconds=DEFAULT_WAIT_SECONDS, source="default")


def put_wait_preference(repo: ScopedRepository, seconds: int, now: datetime) -> WaitPreference:
    set_preference(repo, WAIT_PREFERENCE_KEY, seconds, now)
    return get_wait_preference(repo)


def _signal(repo: ScopedRepository, session_id: str) -> SessionWaitSignalRow | None:
    return repo.db.execute(
        select(SessionWaitSignalRow).where(
            SessionWaitSignalRow.learner_id == repo.learner_id,
            SessionWaitSignalRow.session_id == session_id,
        )
    ).scalar_one_or_none()


def record_still_thinking(repo: ScopedRepository, session_id: str, now: datetime) -> None:
    """Remember an explicit request for space. Repeats only move the timestamp and count."""
    repo.require_session(session_id)
    row = _signal(repo, session_id)
    if row is None:
        repo.db.add(
            SessionWaitSignalRow(
                learner_id=repo.learner_id,
                session_id=session_id,
                still_thinking_at=now,
                still_thinking_count=1,
                updated_at=now,
            )
        )
    else:
        row.still_thinking_at = now
        row.still_thinking_count += 1
        row.updated_at = now
    repo.db.flush()


def _latest(*values: datetime | None) -> datetime:
    present = [value for value in values if value is not None]
    return max(present)


def last_activity_at(repo: ScopedRepository, session_id: str) -> datetime:
    """The learner's or tutor's latest real action in this session (never inferred)."""
    session = repo.require_session(session_id)
    learner = repo.learner_id
    turn_at = repo.db.execute(
        select(func.max(TutorTurnRow.created_at)).where(
            TutorTurnRow.learner_id == learner, TutorTurnRow.session_id == session_id
        )
    ).scalar_one()
    step_at = repo.db.execute(
        select(func.max(StepRow.submitted_at)).where(
            StepRow.learner_id == learner, StepRow.session_id == session_id
        )
    ).scalar_one()
    ink_at = repo.db.execute(
        select(func.max(SceneOperationRow.created_at)).where(
            SceneOperationRow.learner_id == learner,
            SceneOperationRow.session_id == session_id,
            SceneOperationRow.author_role == "student",
        )
    ).scalar_one()
    return _latest(session.started_at, turn_at, step_at, ink_at)


def wait_state(repo: ScopedRepository, session_id: str, now: datetime) -> WaitState:
    preference = get_wait_preference(repo)
    activity = last_activity_at(repo, session_id)
    signal = _signal(repo, session_id)
    still_thinking_at = None if signal is None else signal.still_thinking_at
    # "Still thinking" restarts the quiet period instead of ending it; activity after it
    # supersedes it, because the learner is plainly working.
    quiet_from = _latest(activity, still_thinking_at)
    quiet_hint_at = quiet_from + timedelta(seconds=preference.wait_seconds)
    attempt = open_attempt(repo, session_id)
    levels = [] if attempt is None else [hint.level for hint in attempt_hints(repo, attempt.id)]
    return WaitState(
        session_id=session_id,
        now=now,
        wait_seconds=preference.wait_seconds,
        wait_source=preference.source,
        last_activity_at=activity,
        still_thinking_at=still_thinking_at,
        still_thinking_count=0 if signal is None else signal.still_thinking_count,
        quiet_hint_at=quiet_hint_at,
        quiet_hint_available=now >= quiet_hint_at,
        next_hint_level=next_level(levels),
    )
