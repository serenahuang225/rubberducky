"""Content-free deletion tombstones.

A tombstone records only that an ID was removed (kind, reason, UTC time). It never stores any
text from the removed record, and it has no foreign key to the learner, so it survives
profile deletion. The seed command consults the tombstones so removed fictional history is
not recreated on the next start.

This is active local-store deletion. It is not secure disk, backup or vendor erasure.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import DeletionTombstoneRow
from app.learner.pairing import new_id

TombstoneReason = Literal["learner_deleted", "source_deleted", "session_deleted", "profile_deleted"]
TOMBSTONE_VERSION = "deletion-tombstone.v1"


def record_tombstones(
    db: DbSession,
    learner_id: str,
    records: Iterable[tuple[str, str]],
    reason: TombstoneReason,
    now: datetime,
) -> int:
    """Insert ``(kind, record_id)`` tombstones that are not already present."""
    existing = set(
        db.execute(
            select(DeletionTombstoneRow.record_id).where(
                DeletionTombstoneRow.learner_id == learner_id
            )
        ).scalars()
    )
    written = 0
    for kind, record_id in records:
        if record_id in existing:
            continue
        existing.add(record_id)
        db.add(
            DeletionTombstoneRow(
                id=new_id(),
                schema_version=TOMBSTONE_VERSION,
                learner_id=learner_id,
                record_kind=kind,
                record_id=record_id,
                reason=reason,
                deleted_at=now,
            )
        )
        written += 1
    db.flush()
    return written


def removed_ids(db: DbSession) -> set[str]:
    """Every removed record ID, across learners (used to keep seeds from resurrecting them)."""
    return set(db.execute(select(DeletionTombstoneRow.record_id)).scalars())
