"""Explicit interruption: stop pending tutor output without moving the session revision."""

from datetime import datetime

from app.db.repositories import ScopedRepository
from app.schemas.tutor import InterruptRequest, InterruptResult
from app.tutor.cancellation import (
    EPOCH_CHANGED,
    claim_epoch,
    current_epoch,
    settle_pending_turns,
)
from app.tutor.coordinator import TurnCommandError


def interrupt_session(
    repo: ScopedRepository, session_id: str, body: InterruptRequest, now: datetime
) -> InterruptResult:
    """Advance the cancellation epoch once per observed epoch and withdraw pending turns.

    The compare-and-swap on the epoch makes a retried request (lost acknowledgment) or a
    concurrent duplicate report ``replayed`` rather than cancelling again, so a turn started
    after the first interrupt is never cancelled by a late retry of it.
    """
    session = repo.require_session(session_id)
    if session.status != "active":
        raise TurnCommandError("session_not_active", "The session is not active.")
    interrupted: list[str] = []
    replayed = False
    if claim_epoch(repo, session_id, body.observed_epoch):
        interrupted = settle_pending_turns(
            repo,
            session_id,
            status="superseded",
            rejection=EPOCH_CHANGED,
            now=now,
            bump=False,
        )
    else:
        epoch = current_epoch(repo, session_id)
        if epoch < body.observed_epoch:
            raise TurnCommandError(
                "epoch_conflict",
                f"The session is at cancellation epoch {epoch}, not {body.observed_epoch}.",
            )
        replayed = True
    repo.db.refresh(session)
    return InterruptResult(
        session_id=session_id,
        cancellation_epoch=session.cancellation_epoch,
        session_revision=session.revision,
        interrupted_turn_ids=interrupted,
        replayed=replayed,
    )
