"""Cancellation epoch, superseding pending turns, in-flight provider cancel and restart recovery.

A tutor turn may only commit under the cancellation epoch it was reserved in. The epoch
advances whenever pending tutor output is invalidated: an explicit interrupt, newer student
work, a corrected or deleted source, a new problem, or a process restart. Invalidated turns
become ``superseded`` (or ``failed`` after a restart) in the same transaction as the bump,
so a late provider response finds a non-pending turn and can add no text, mark, hint,
evidence or memory. The student's own raw evidence, recorded when the turn was reserved,
always survives; only the tutor's reply is withdrawn.
"""

import threading
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from app.db.database import Database
from app.db.models import SessionRow, TutorTurnRow
from app.db.repositories import ScopedRepository
from app.inference.cancel import CancelToken
from app.learner.pairing import LearnerScope
from app.schemas.tutor import StudentInputOutcome, TurnRejection, TutorTurnResult
from app.tracing.replay import replay_learner

REVISION_CHANGED = TurnRejection(
    code="revision_changed",
    message="The session changed while this turn was being prepared.",
)
EPOCH_CHANGED = TurnRejection(
    code="interrupted",
    message="This reply was stopped before it finished; nothing from it was kept.",
)
SUPERSEDED_BY_WORK = TurnRejection(
    code="superseded_by_work",
    message="Newer work arrived before this reply finished, so it was dropped.",
)
RESTART_INTERRUPTED = TurnRejection(
    code="restart_interrupted",
    message=(
        "The server restarted before this reply finished. Your work is saved; "
        "ask again or press Help."
    ),
)


class InflightTurns:
    """Process-local cancel tokens for provider calls that are currently running.

    Persistence is the authority (a cancelled turn is no longer ``pending``); this only lets
    a cooperative provider stop early instead of finishing a reply nobody will see.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, CancelToken] = {}

    def register(self, turn_id: str) -> CancelToken:
        token = CancelToken()
        with self._lock:
            self._tokens[turn_id] = token
        return token

    def release(self, turn_id: str) -> None:
        with self._lock:
            self._tokens.pop(turn_id, None)

    def cancel(self, turn_ids: Iterable[str], reason: str) -> None:
        with self._lock:
            tokens = [self._tokens[i] for i in turn_ids if i in self._tokens]
        for token in tokens:
            token.cancel(reason)


INFLIGHT = InflightTurns()


def current_epoch(repo: ScopedRepository, session_id: str) -> int:
    return int(
        repo.db.execute(
            select(SessionRow.cancellation_epoch).where(
                SessionRow.id == session_id, SessionRow.learner_id == repo.learner_id
            )
        ).scalar_one()
    )


def bump_epoch(repo: ScopedRepository, session_id: str) -> int:
    """Advance the session's cancellation epoch (atomically, in the caller's transaction)."""
    repo.db.execute(
        update(SessionRow)
        .where(SessionRow.id == session_id, SessionRow.learner_id == repo.learner_id)
        .values(cancellation_epoch=SessionRow.cancellation_epoch + 1)
        .execution_options(synchronize_session=False)
    )
    repo.db.flush()
    return current_epoch(repo, session_id)


def claim_epoch(repo: ScopedRepository, session_id: str, observed: int) -> bool:
    """Advance the epoch only if it still equals ``observed`` (compare-and-swap)."""
    result = repo.db.execute(
        update(SessionRow)
        .where(
            SessionRow.id == session_id,
            SessionRow.learner_id == repo.learner_id,
            SessionRow.cancellation_epoch == observed,
        )
        .values(cancellation_epoch=SessionRow.cancellation_epoch + 1)
        .execution_options(synchronize_session=False)
    )
    repo.db.flush()
    return cast(CursorResult[Any], result).rowcount == 1


def _fill_update_status(
    student_input: StudentInputOutcome | None, updates: Mapping[str, str]
) -> StudentInputOutcome | None:
    if student_input is None:
        return None
    return student_input.model_copy(
        update={
            "eligibility": [
                note.model_copy(update={"update_status": updates.get(note.observation_id)})
                for note in student_input.eligibility
            ]
        }
    )


def settle_pending_turns(
    repo: ScopedRepository,
    session_id: str,
    *,
    status: Literal["superseded", "failed"],
    rejection: TurnRejection,
    now: datetime,
    bump: bool = True,
    replay: bool = True,
) -> list[str]:
    """Withdraw every still-pending turn of one session; returns their ids.

    ``replay`` rewrites derived BKT rows from the raw evidence the withdrawn turns already
    recorded (a committed turn would have done this), so withdrawing a reply never leaves
    estimates out of step with durable evidence.
    """
    rows = list(
        repo.db.execute(
            select(TutorTurnRow)
            .where(
                TutorTurnRow.learner_id == repo.learner_id,
                TutorTurnRow.session_id == session_id,
                TutorTurnRow.status == "pending",
            )
            .order_by(TutorTurnRow.created_at, TutorTurnRow.id)
        ).scalars()
    )
    if not rows:
        return []
    if bump:
        bump_epoch(repo, session_id)
    updates: dict[str, str] = {}
    if replay:
        _, report = replay_learner(repo.db, repo.learner_id, now)
        updates = {u.observation_id: u.status for u in report.updates}
    epoch = current_epoch(repo, session_id)
    for row in rows:
        result = TutorTurnResult.model_validate(row.result).model_copy(
            update={"status": status, "completed_at": now, "cancellation_epoch": epoch}
        )
        result = result.model_copy(
            update={
                "rejections": [*result.rejections, rejection],
                "student_input": _fill_update_status(result.student_input, updates),
            }
        )
        row.status = status
        row.completed_at = now
        row.result = result.model_dump(mode="json")
    repo.db.flush()
    return [row.id for row in rows]


def recover_pending_turns(database: Database, now: datetime) -> list[str]:
    """Mark turns left pending by a previous process as failed, never as finished.

    Called once at startup. The provider call died with the process, so its reply cannot
    arrive; leaving the turn pending would show "thinking" forever. The student's recorded
    work stays. A retry with the same idempotency key may resume the turn (see the
    coordinator), so a lost acknowledgment across a restart is still exactly-once.
    """
    with database.transaction() as db:
        pairs = sorted(
            set(
                db.execute(
                    select(TutorTurnRow.learner_id, TutorTurnRow.session_id).where(
                        TutorTurnRow.status == "pending"
                    )
                ).all()
            )
        )
        recovered: list[str] = []
        for learner_id, session_id in pairs:
            repo = ScopedRepository(
                db, LearnerScope(learner_id=learner_id, credential_id="restart")
            )
            recovered += settle_pending_turns(
                repo, session_id, status="failed", rejection=RESTART_INTERRUPTED, now=now
            )
        return recovered
