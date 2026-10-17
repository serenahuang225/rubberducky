"""Read and edit the six memory layers for one scoped learner.

Raw evidence and derived beliefs are written by the evidence and tracing services; this
module only reads them. Preferences are edited by the learner (or a local operator), never
by a provider. Session context and episodic notes are filtered by status, expiry and the
current session at read time, so stale context cannot leak even before a sweep runs.
"""

from datetime import datetime

from sqlalchemy import select

from app.db.models import (
    MasteryEstimateRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    PreferenceRow,
    SessionRow,
)
from app.db.repositories import ScopedRepository
from app.learner.pairing import new_id
from app.schemas import (
    MasteryEstimate,
    MemoryEntry,
    MisconceptionHypothesis,
    Observation,
    Preference,
)
from app.schemas.learner import PreferenceEditor, PreferenceValue
from app.schemas.memory import (
    MAX_LAYER_ITEMS,
    EpisodicNote,
    MemoryLayers,
    SessionContextLayer,
)

USABLE_NOTE_STATUSES = ("active",)


def _is_live(row: MemoryEntryRow, now: datetime) -> bool:
    return row.status == "active" and (row.expires_at is None or row.expires_at > now)


def non_current_memory_ids(repo: ScopedRepository) -> frozenset[str]:
    """IDs of the learner's memory entries that are corrected, flagged, expired or retracted.

    Replacement notes keep their original's ID as lineage in ``source_ids``; that lineage is
    for inspection, not permission to cite the excluded wording as current evidence.
    """
    return frozenset(
        repo.db.execute(
            select(MemoryEntryRow.id).where(
                MemoryEntryRow.learner_id == repo.learner_id,
                MemoryEntryRow.status != "active",
            )
        ).scalars()
    )


def active_session_context(
    repo: ScopedRepository, session_id: str | None, now: datetime
) -> list[MemoryEntry]:
    """Session context that applies right now: same session, active, open, unexpired."""
    if session_id is None:
        return []
    session = repo.require_session(session_id)
    if session.status != "active":
        return []
    rows = repo.db.execute(
        select(MemoryEntryRow)
        .where(
            MemoryEntryRow.learner_id == repo.learner_id,
            MemoryEntryRow.layer == "session_context",
            MemoryEntryRow.session_id == session_id,
        )
        .order_by(MemoryEntryRow.created_at.desc(), MemoryEntryRow.id)
        .limit(MAX_LAYER_ITEMS)
    ).scalars()
    return [MemoryEntry.model_validate(row) for row in rows if _is_live(row, now)]


def stale_session_context_count(
    repo: ScopedRepository, session_id: str | None, now: datetime
) -> int:
    """Session context from other sessions, or already expired: it must be rechecked."""
    rows = repo.db.execute(
        select(MemoryEntryRow).where(
            MemoryEntryRow.learner_id == repo.learner_id,
            MemoryEntryRow.layer == "session_context",
            MemoryEntryRow.status.in_(("active", "needs_review", "expired")),
        )
    ).scalars()
    return sum(1 for row in rows if row.session_id != session_id or not _is_live(row, now))


def episodic_notes(
    repo: ScopedRepository, now: datetime, limit: int = MAX_LAYER_ITEMS
) -> list[EpisodicNote]:
    """Notes that are not deleted or expired, newest first, with their review state."""
    rows = repo.db.execute(
        select(MemoryEntryRow)
        .where(
            MemoryEntryRow.learner_id == repo.learner_id,
            MemoryEntryRow.layer == "episodic_note",
            MemoryEntryRow.status.in_(("active", "needs_review", "corrected")),
        )
        .order_by(MemoryEntryRow.created_at.desc(), MemoryEntryRow.id)
    ).scalars()
    notes = [
        EpisodicNote(
            entry=MemoryEntry.model_validate(row),
            review_due=row.status == "needs_review"
            or (row.review_at is not None and row.review_at <= now),
        )
        for row in rows
        if row.expires_at is None or row.expires_at > now
    ]
    return notes[: max(1, min(limit, MAX_LAYER_ITEMS))]


def usable_notes(repo: ScopedRepository, now: datetime) -> tuple[list[MemoryEntry], int]:
    """Active notes not yet due for review, plus how many others were held back."""
    notes = episodic_notes(repo, now)
    usable = [n.entry for n in notes if n.entry.status == "active" and not n.review_due]
    return usable, len(notes) - len(usable)


def preferences(repo: ScopedRepository) -> list[Preference]:
    rows = repo.db.execute(
        select(PreferenceRow)
        .where(PreferenceRow.learner_id == repo.learner_id)
        .order_by(PreferenceRow.key)
        .limit(MAX_LAYER_ITEMS)
    ).scalars()
    return [Preference.model_validate(row) for row in rows]


def set_preference(
    repo: ScopedRepository,
    key: str,
    value: PreferenceValue,
    now: datetime,
    updated_by: PreferenceEditor = "learner",
) -> Preference:
    """Create or replace one of the learner's own preferences (a deliberate learner edit)."""
    row = repo.db.execute(
        select(PreferenceRow).where(
            PreferenceRow.learner_id == repo.learner_id, PreferenceRow.key == key
        )
    ).scalar_one_or_none()
    preference = Preference(
        id=row.id if row is not None else new_id(),
        learner_id=repo.learner_id,
        key=key,
        value=value,
        provenance="submitted",
        updated_by=updated_by,
        updated_at=now,
    )
    if row is None:
        repo.db.add(PreferenceRow(**preference.model_dump()))
    else:
        for field, field_value in preference.model_dump().items():
            setattr(row, field, field_value)
    repo.db.flush()
    return preference


def latest_estimates(
    repo: ScopedRepository, concept_ids: list[str] | None = None
) -> list[MasteryEstimate]:
    query = select(MasteryEstimateRow).where(MasteryEstimateRow.learner_id == repo.learner_id)
    if concept_ids is not None:
        query = query.where(MasteryEstimateRow.concept_id.in_(concept_ids))
    rows = repo.db.execute(
        query.order_by(MasteryEstimateRow.computed_at.desc(), MasteryEstimateRow.id)
    ).scalars()
    latest: dict[str, MasteryEstimate] = {}
    for row in rows:
        latest.setdefault(row.concept_id, MasteryEstimate.model_validate(row))
    return [latest[cid] for cid in sorted(latest)][:MAX_LAYER_ITEMS]


def memory_layers(
    repo: ScopedRepository,
    now: datetime,
    session_id: str | None = None,
    limit: int = 20,
) -> MemoryLayers:
    bounded = max(1, min(limit, MAX_LAYER_ITEMS))
    if session_id is None:
        current = repo.db.execute(
            select(SessionRow.id)
            .where(SessionRow.learner_id == repo.learner_id, SessionRow.status == "active")
            .order_by(SessionRow.started_at.desc(), SessionRow.id)
            .limit(1)
        ).scalar_one_or_none()
    else:
        current = repo.require_session(session_id).id
    observations = repo.db.execute(
        select(ObservationRow)
        .where(ObservationRow.learner_id == repo.learner_id)
        .order_by(ObservationRow.observed_at.desc(), ObservationRow.id)
        .limit(bounded)
    ).scalars()
    hypotheses = repo.db.execute(
        select(MisconceptionHypothesisRow)
        .where(MisconceptionHypothesisRow.learner_id == repo.learner_id)
        .order_by(MisconceptionHypothesisRow.updated_at.desc(), MisconceptionHypothesisRow.id)
        .limit(bounded)
    ).scalars()
    active = active_session_context(repo, current, now)
    stale = stale_session_context_count(repo, current, now)
    return MemoryLayers(
        learner_id=repo.learner_id,
        generated_at=now,
        limit=bounded,
        raw_evidence=[Observation.model_validate(row) for row in observations],
        derived_hypotheses=[MisconceptionHypothesis.model_validate(row) for row in hypotheses],
        derived_estimates=latest_estimates(repo)[:bounded],
        preferences=preferences(repo)[:bounded],
        session_context=SessionContextLayer(
            current_session_id=current,
            active=active[:bounded],
            expired_count=stale,
            recheck_needed=stale > 0 and not active,
        ),
        episodic_notes=episodic_notes(repo, now, bounded),
        persona=repo.tutor_configuration(),
    )
