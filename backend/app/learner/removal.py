"""Remove one session, or a whole learner profile, from the active local store.

Session removal deletes the session's work, observations, hints, assessments, hypotheses,
notes, scene objects/operations, turns and wait signals (database cascades), then follows
the IDs it removed into other sessions: beliefs and notes that cited them are deleted and BKT
is replayed from what remains. Profile removal revokes every credential and deletes the learner
row, which cascades to all learner-owned tables. Other learners and the shared curriculum are
never touched. Tombstones keep the fictional seed from recreating removed history.

This is active local-store deletion, not secure disk, backup or vendor erasure.
"""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app.db.models import (
    AssessmentRow,
    AttemptRow,
    Base,
    HintRow,
    LearnerRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SessionRow,
    StepRow,
    TutorTurnRow,
)
from app.db.repositories import ScopedRepository
from app.learner.corrections import tombstone_count
from app.learner.derived import Tally, propagate_removal, recompute_mastery, settle_turns
from app.learner.pairing import revoke_all_for_learner
from app.learner.tombstones import record_tombstones
from app.schemas.agency import DerivedEffects, RemovalReceipt

# Tombstones are the retained record of deletion, so they are not part of the learner's data.
_LEARNER_TABLES = [
    table
    for table in Base.metadata.sorted_tables
    if "learner_id" in table.c and table.name != "deletion_tombstones"
]
_SESSION_RECORDS: tuple[tuple[str, type[Base]], ...] = (
    ("attempt", AttemptRow),
    ("step", StepRow),
    ("observation", ObservationRow),
    ("hint", HintRow),
    ("assessment", AssessmentRow),
    ("hypothesis", MisconceptionHypothesisRow),
    ("memory_entry", MemoryEntryRow),
    ("turn", TutorTurnRow),
)


def learner_inventory(db: DbSession, learner_id: str) -> dict[str, int]:
    """Row counts of every learner-owned store, for before/after removal receipts."""
    counts = {
        "learners": int(
            db.execute(
                select(func.count()).select_from(LearnerRow).where(LearnerRow.id == learner_id)
            ).scalar_one()
        )
    }
    for table in _LEARNER_TABLES:
        counts[table.name] = int(
            db.execute(
                select(func.count()).select_from(table).where(table.c.learner_id == learner_id)
            ).scalar_one()
        )
    return counts


def delete_session(repo: ScopedRepository, session_id: str, now: datetime) -> RemovalReceipt:
    session = repo.require_session(session_id)
    before = learner_inventory(repo.db, repo.learner_id)
    records: list[tuple[str, str]] = [("session", session.id)]
    for kind, model in _SESSION_RECORDS:
        ids = repo.db.execute(
            select(model.id).where(  # type: ignore[attr-defined]
                model.learner_id == repo.learner_id,  # type: ignore[attr-defined]
                model.session_id == session.id,  # type: ignore[attr-defined]
            )
        ).scalars()
        records.extend((kind, record_id) for record_id in ids)
    written_before = tombstone_count(repo)
    record_tombstones(repo.db, repo.learner_id, records, "session_deleted", now)
    removed = {record_id for _, record_id in records}
    repo.db.flush()
    repo.db.execute(
        delete(SessionRow).where(
            SessionRow.id == session.id, SessionRow.learner_id == repo.learner_id
        ),
        execution_options={"synchronize_session": False},
    )
    repo.db.flush()
    repo.db.expire_all()
    tally = Tally()
    removed = propagate_removal(repo, removed, now, tally)
    settle_turns(repo, removed, now, tally)
    recompute_mastery(repo, now, tally)
    return RemovalReceipt(
        scope="session",
        record_id=session_id,
        before=before,
        after=learner_inventory(repo.db, repo.learner_id),
        tombstones_written=tombstone_count(repo) - written_before,
        effects=tally.effects(repo),
    )


def delete_profile(repo: ScopedRepository, now: datetime) -> RemovalReceipt:
    learner_id = repo.learner_id
    before = learner_inventory(repo.db, learner_id)
    revoked = revoke_all_for_learner(repo.db, learner_id, now)
    record_tombstones(repo.db, learner_id, [("learner", learner_id)], "profile_deleted", now)
    repo.db.flush()
    # The learner FK cascades to every learner-owned table, including credentials and
    # pairing codes (so an unredeemed code cannot recreate access).
    repo.db.execute(
        delete(LearnerRow).where(LearnerRow.id == learner_id),
        execution_options={"synchronize_session": False},
    )
    repo.db.flush()
    repo.db.expire_all()
    return RemovalReceipt(
        scope="profile",
        record_id=learner_id,
        before=before,
        after=learner_inventory(repo.db, learner_id),
        credentials_revoked=revoked,
        tombstones_written=1,
        effects=DerivedEffects(),
    )
