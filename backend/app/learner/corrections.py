"""Learner corrections and deletions of evidence, notes and hypotheses.

A correction never overwrites history silently. Evidence keeps its original value in a
separate correction row; a corrected note is superseded by a learner-authored entry whose
provenance is distinct (``origin='learner'``, ``supersedes_id``). Deletion removes the
content from the active store and keeps only a content-free tombstone. Every operation then
invalidates dependents and recomputes BKT from the remaining raw evidence (see
``app.learner.derived``).
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from app.db.models import (
    AssessmentRow,
    DeletionTombstoneRow,
    EvidenceCorrectionRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    StepRow,
)
from app.db.repositories import ScopedRepository
from app.learner.derived import (
    Tally,
    propagate_change,
    propagate_removal,
    recompute_mastery,
    settle_turns,
)
from app.learner.pairing import new_id
from app.learner.tombstones import record_tombstones
from app.schemas import MemoryEntry
from app.schemas.agency import CorrectionReceipt, DeletionReceipt, ItemKind

LEARNER_CORRECTION_CONFIDENCE = 0.9
CORRECTED_NOTE_REVIEW = timedelta(days=30)
# Observation sources whose ID names a record that should go with the observation.
_OWNED_SOURCES = ("step", "assessment", "help_request")


class CorrectionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def tombstone_count(repo: ScopedRepository) -> int:
    return int(
        repo.db.execute(
            select(func.count())
            .select_from(DeletionTombstoneRow)
            .where(DeletionTombstoneRow.learner_id == repo.learner_id)
        ).scalar_one()
    )


def _evidence_records(
    repo: ScopedRepository, observation: ObservationRow
) -> tuple[AssessmentRow | None, list[StepRow]]:
    """The assessment and typed work a verified observation was produced from."""
    db = repo.db
    if observation.source_type == "step":
        step = db.execute(
            select(StepRow).where(
                StepRow.id == observation.source_id, StepRow.learner_id == repo.learner_id
            )
        ).scalar_one_or_none()
        return None, [] if step is None else [step]
    if observation.source_type != "assessment":
        return None, []
    assessment = db.execute(
        select(AssessmentRow).where(
            AssessmentRow.id == observation.source_id,
            AssessmentRow.learner_id == repo.learner_id,
        )
    ).scalar_one_or_none()
    if assessment is None:
        return None, []
    # The submission that was assessed is stored at the same instant in the same attempt.
    steps = list(
        db.execute(
            select(StepRow).where(
                StepRow.learner_id == repo.learner_id,
                StepRow.attempt_id == assessment.attempt_id,
                StepRow.submitted_at == assessment.assessed_at,
            )
        ).scalars()
    )
    return assessment, steps


def _source_ids(
    observation: ObservationRow, assessment: AssessmentRow | None, steps: list[StepRow]
) -> set[str]:
    ids = {observation.id, *(step.id for step in steps)}
    if assessment is not None:
        ids.add(assessment.id)
    if observation.source_type in _OWNED_SOURCES:
        ids.add(observation.source_id)
    return ids


def _label(value: bool) -> str:
    return "correct" if value else "not correct"


def correct_evidence(
    repo: ScopedRepository, observation_id: str, correct: bool, now: datetime
) -> CorrectionReceipt:
    observation = repo.require_observation(observation_id)
    if observation.correct is None:
        raise CorrectionError(
            "not_correctable",
            "Only evidence that was judged correct or not correct can be corrected.",
        )
    assessment, steps = _evidence_records(repo, observation)
    existing = repo.db.execute(
        select(EvidenceCorrectionRow).where(
            EvidenceCorrectionRow.learner_id == repo.learner_id,
            EvidenceCorrectionRow.observation_id == observation.id,
        )
    ).scalar_one_or_none()
    original = observation.correct if existing is None else existing.original_correct
    if observation.correct == correct:
        return CorrectionReceipt(
            kind="evidence",
            record_id=observation.id,
            changed=False,
            original=_label(original),
            current=_label(observation.correct),
            effects=Tally().effects(repo),
        )
    if existing is None:
        repo.db.add(
            EvidenceCorrectionRow(
                id=new_id(),
                schema_version="evidence-correction.v1",
                learner_id=repo.learner_id,
                observation_id=observation.id,
                original_correct=observation.correct,
                corrected_correct=correct,
                original_assessment_outcome=None if assessment is None else assessment.outcome,
                provenance="submitted",
                corrected_at=now,
            )
        )
    else:
        existing.corrected_correct = correct
        existing.corrected_at = now
    observation.correct = correct
    if assessment is not None:
        # Eligibility compares the assessment outcome with the observation, so both follow
        # the learner's correction; the original outcome stays on the correction row.
        assessment.outcome = "correct" if correct else "incorrect"
    repo.db.flush()
    tally = Tally()
    changed = _source_ids(observation, assessment, steps)
    propagate_change(repo, changed, now, tally)
    settle_turns(repo, set(), now, tally)
    recompute_mastery(repo, now, tally)
    return CorrectionReceipt(
        kind="evidence",
        record_id=observation.id,
        changed=True,
        original=_label(original),
        current=_label(correct),
        effects=tally.effects(repo),
    )


def _renumber_steps(repo: ScopedRepository, attempt_ids: set[str]) -> None:
    """Close sequence gaps so the next submission in an attempt cannot collide."""
    for attempt_id in attempt_ids:
        steps = list(
            repo.db.execute(
                select(StepRow)
                .where(StepRow.attempt_id == attempt_id, StepRow.learner_id == repo.learner_id)
                .order_by(StepRow.sequence)
            ).scalars()
        )
        for index, step in enumerate(steps):
            if step.sequence != index:
                step.sequence = index
                repo.db.flush()


def delete_evidence(repo: ScopedRepository, observation_id: str, now: datetime) -> DeletionReceipt:
    observation = repo.require_observation(observation_id)
    assessment, steps = _evidence_records(repo, observation)
    ids = _source_ids(observation, assessment, steps)
    before = tombstone_count(repo)
    records = [("observation", observation.id), *(("step", step.id) for step in steps)]
    if assessment is not None:
        records.append(("assessment", assessment.id))
    record_tombstones(repo.db, repo.learner_id, records, "learner_deleted", now)
    attempt_ids = {step.attempt_id for step in steps}
    repo.db.flush()
    # Cascades remove the observation's evidence links, BKT ledger rows and correction row.
    repo.db.execute(
        delete(ObservationRow).where(
            ObservationRow.id == observation.id, ObservationRow.learner_id == repo.learner_id
        ),
        execution_options={"synchronize_session": False},
    )
    for step in steps:
        repo.db.execute(
            delete(StepRow).where(StepRow.id == step.id, StepRow.learner_id == repo.learner_id),
            execution_options={"synchronize_session": False},
        )
    if assessment is not None:
        repo.db.execute(
            delete(AssessmentRow).where(
                AssessmentRow.id == assessment.id, AssessmentRow.learner_id == repo.learner_id
            ),
            execution_options={"synchronize_session": False},
        )
    repo.db.flush()
    repo.db.expire_all()
    _renumber_steps(repo, attempt_ids)
    tally = Tally()
    removed = propagate_removal(repo, ids, now, tally)
    settle_turns(repo, removed, now, tally)
    recompute_mastery(repo, now, tally)
    return DeletionReceipt(
        kind="evidence",
        record_id=observation_id,
        deleted_ids=sorted(removed),
        tombstones_written=tombstone_count(repo) - before,
        effects=tally.effects(repo),
    )


def correct_note(
    repo: ScopedRepository, memory_id: str, content: str, now: datetime
) -> CorrectionReceipt:
    row = repo.require_memory_entry(memory_id)
    if row.status not in ("active", "needs_review"):
        raise CorrectionError("not_correctable", "Only a current note can be corrected.")
    kind: ItemKind = "note" if row.layer == "episodic_note" else "session_context"
    original = row.content
    # Dependents are flagged before the replacement exists, so it is not flagged itself.
    tally = Tally()
    propagate_change(repo, {row.id}, now, tally)
    row.status = "corrected"
    row.updated_at = now
    review_at = None
    if row.layer == "episodic_note":
        review_at = now + CORRECTED_NOTE_REVIEW
        if row.expires_at is not None:
            review_at = min(review_at, row.expires_at)
    replacement = MemoryEntry(
        id=new_id(),
        learner_id=repo.learner_id,
        session_id=row.session_id,
        layer=row.layer,  # type: ignore[arg-type]
        content=content,
        evidence_kind="self_report",
        confidence=LEARNER_CORRECTION_CONFIDENCE,
        source_ids=[row.id],
        status="active",
        review_at=review_at,
        expires_at=row.expires_at,
        origin="learner",
        turn_id=None,
        supersedes_id=row.id,
        provenance="submitted",
        created_at=now,
        updated_at=now,
    )
    repo.db.add(MemoryEntryRow(**replacement.model_dump()))
    repo.db.flush()
    settle_turns(repo, set(), now, tally)
    return CorrectionReceipt(
        kind=kind,
        record_id=memory_id,
        changed=True,
        replacement_id=replacement.id,
        original=original[:500],
        current=content,
        effects=tally.effects(repo),
    )


def _note_chain(repo: ScopedRepository, memory_id: str) -> set[str]:
    """Every version of a note: what it superseded and whatever superseded it."""
    entries = {
        entry.id: entry
        for entry in repo.db.execute(
            select(MemoryEntryRow).where(MemoryEntryRow.learner_id == repo.learner_id)
        ).scalars()
    }
    chain = {memory_id}
    grew = True
    while grew:
        grew = False
        for entry in entries.values():
            linked = entry.id in chain or entry.supersedes_id in chain
            if linked and entry.id not in chain:
                chain.add(entry.id)
                grew = True
            if entry.id in chain and entry.supersedes_id and entry.supersedes_id not in chain:
                chain.add(entry.supersedes_id)
                grew = True
    return chain & set(entries)


def delete_note(repo: ScopedRepository, memory_id: str, now: datetime) -> DeletionReceipt:
    row = repo.require_memory_entry(memory_id)
    kind: ItemKind = "note" if row.layer == "episodic_note" else "session_context"
    chain = _note_chain(repo, row.id)
    before = tombstone_count(repo)
    record_tombstones(
        repo.db,
        repo.learner_id,
        [("memory_entry", item) for item in sorted(chain)],
        "learner_deleted",
        now,
    )
    repo.db.execute(
        delete(MemoryEntryRow).where(
            MemoryEntryRow.id.in_(chain), MemoryEntryRow.learner_id == repo.learner_id
        ),
        execution_options={"synchronize_session": False},
    )
    repo.db.flush()
    repo.db.expire_all()
    tally = Tally()
    removed = propagate_removal(repo, chain, now, tally)
    settle_turns(repo, removed, now, tally)
    return DeletionReceipt(
        kind=kind,
        record_id=memory_id,
        deleted_ids=sorted(removed),
        tombstones_written=tombstone_count(repo) - before,
        effects=tally.effects(repo),
    )


def delete_hypothesis(repo: ScopedRepository, hypothesis_id: str, now: datetime) -> DeletionReceipt:
    row = repo.require_hypothesis(hypothesis_id)
    before = tombstone_count(repo)
    record_tombstones(repo.db, repo.learner_id, [("hypothesis", row.id)], "learner_deleted", now)
    repo.db.execute(
        delete(MisconceptionHypothesisRow).where(
            MisconceptionHypothesisRow.id == row.id,
            MisconceptionHypothesisRow.learner_id == repo.learner_id,
        ),
        execution_options={"synchronize_session": False},
    )
    repo.db.flush()
    repo.db.expire_all()
    tally = Tally()
    removed = propagate_removal(repo, {hypothesis_id}, now, tally)
    settle_turns(repo, removed, now, tally)
    return DeletionReceipt(
        kind="hypothesis",
        record_id=hypothesis_id,
        deleted_ids=sorted(removed),
        tombstones_written=tombstone_count(repo) - before,
        effects=tally.effects(repo),
    )
