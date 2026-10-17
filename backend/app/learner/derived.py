"""Invalidate and recompute everything derived from a changed or removed source.

Raw evidence is the only input to BKT, so a corrected or deleted observation is repaired by
replaying the remaining raw history from ``p_init`` for every stored parameter version, never
by nudging an old posterior. Hypotheses, notes and tutor-turn caches that cite the changed
source are retracted, flagged for review or removed so they cannot be retrieved or reused.
Dependencies are followed to a fixed point because a note may cite a hypothesis that cited
the source.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from app.db.models import (
    BKTCountedOpportunityRow,
    MasteryEstimateRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    TutorTurnRow,
)
from app.db.repositories import ScopedRepository
from app.learner.memory import latest_estimates
from app.learner.tombstones import record_tombstones
from app.schemas.agency import DerivedEffects
from app.schemas.tutor import StudentInputOutcome, TurnRejection, TutorTurnResult
from app.tracing.contracts import DEFAULT_PARAMETERS
from app.tracing.replay import replay_learner
from app.tutor.cancellation import INFLIGHT, bump_epoch

SOURCE_CHANGED = TurnRejection(
    code="source_changed",
    message="A source this turn depended on was corrected or deleted.",
)
# Cached provider-context citations are listed here; other result fields are the turn's content.
_CONTEXT_KEY = "context_source_ids"


@dataclass
class Tally:
    hypotheses_retracted: list[str] = field(default_factory=list)
    hypotheses_deleted: list[str] = field(default_factory=list)
    notes_flagged_for_review: list[str] = field(default_factory=list)
    notes_deleted: list[str] = field(default_factory=list)
    turns_deleted: list[str] = field(default_factory=list)
    pending_turns_invalidated: list[str] = field(default_factory=list)
    recomputed_parameter_versions: list[str] = field(default_factory=list)

    def effects(self, repo: ScopedRepository | None = None) -> DerivedEffects:
        estimates = latest_estimates(repo) if repo is not None else []
        return DerivedEffects(
            hypotheses_retracted=self.hypotheses_retracted,
            hypotheses_deleted=self.hypotheses_deleted,
            notes_flagged_for_review=self.notes_flagged_for_review,
            notes_deleted=self.notes_deleted,
            turns_deleted=self.turns_deleted,
            pending_turns_invalidated=self.pending_turns_invalidated,
            recomputed_parameter_versions=self.recomputed_parameter_versions,
            mastery_estimates=estimates,
        )


def _string_leaves(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_string_leaves(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_string_leaves(item) for item in value)) if value else set()
    return set()


def _own_hypotheses(repo: ScopedRepository) -> list[MisconceptionHypothesisRow]:
    return list(
        repo.db.execute(
            select(MisconceptionHypothesisRow)
            .where(MisconceptionHypothesisRow.learner_id == repo.learner_id)
            .order_by(MisconceptionHypothesisRow.created_at, MisconceptionHypothesisRow.id)
        ).scalars()
    )


def _own_entries(repo: ScopedRepository) -> list[MemoryEntryRow]:
    return list(
        repo.db.execute(
            select(MemoryEntryRow)
            .where(MemoryEntryRow.learner_id == repo.learner_id)
            .order_by(MemoryEntryRow.created_at, MemoryEntryRow.id)
        ).scalars()
    )


def propagate_removal(
    repo: ScopedRepository, removed: set[str], now: datetime, tally: Tally
) -> set[str]:
    """Delete hypotheses and memory entries that cite a removed ID, to a fixed point.

    Returns every ID now removed (the input plus the cascade). A removed correction also
    removes the entry it superseded, and the reverse, so no version of deleted content stays.
    """
    all_removed = set(removed)
    frontier = set(removed)
    chain_targets: set[str] = set()
    while frontier:
        found: set[str] = set()
        for hypothesis in _own_hypotheses(repo):
            if hypothesis.id in all_removed or not set(hypothesis.source_ids) & frontier:
                continue
            found.add(hypothesis.id)
            tally.hypotheses_deleted.append(hypothesis.id)
            record_tombstones(
                repo.db,
                repo.learner_id,
                [("hypothesis", hypothesis.id)],
                "source_deleted",
                now,
            )
            # Evidence links cascade with the hypothesis.
            repo.db.execute(
                delete(MisconceptionHypothesisRow).where(
                    MisconceptionHypothesisRow.id == hypothesis.id,
                    MisconceptionHypothesisRow.learner_id == repo.learner_id,
                ),
                execution_options={"synchronize_session": False},
            )
        for entry in _own_entries(repo):
            chained = entry.id in chain_targets or entry.supersedes_id in all_removed | found
            if entry.id in all_removed or not (set(entry.source_ids) & frontier or chained):
                continue
            found.add(entry.id)
            tally.notes_deleted.append(entry.id)
            if entry.supersedes_id is not None:
                chain_targets.add(entry.supersedes_id)
            record_tombstones(
                repo.db, repo.learner_id, [("memory_entry", entry.id)], "source_deleted", now
            )
            repo.db.execute(
                delete(MemoryEntryRow).where(
                    MemoryEntryRow.id == entry.id,
                    MemoryEntryRow.learner_id == repo.learner_id,
                ),
                execution_options={"synchronize_session": False},
            )
        repo.db.flush()
        repo.db.expire_all()
        frontier = found - all_removed
        all_removed |= found
    return all_removed


def propagate_change(
    repo: ScopedRepository, changed: set[str], now: datetime, tally: Tally
) -> None:
    """Retract hypotheses and hold notes that cite a corrected source, to a fixed point."""
    seen = set(changed)
    frontier = set(changed)
    while frontier:
        found: set[str] = set()
        for hypothesis in _own_hypotheses(repo):
            if hypothesis.status == "retracted" or not set(hypothesis.source_ids) & frontier:
                continue
            hypothesis.status = "retracted"
            hypothesis.updated_at = now
            tally.hypotheses_retracted.append(hypothesis.id)
            found.add(hypothesis.id)
        for entry in _own_entries(repo):
            if entry.status != "active" or not set(entry.source_ids) & frontier:
                continue
            entry.status = "needs_review"
            entry.updated_at = now
            tally.notes_flagged_for_review.append(entry.id)
            found.add(entry.id)
        repo.db.flush()
        frontier = found - seen
        seen |= found


def _redact(result: TutorTurnResult, removed: set[str]) -> TutorTurnResult:
    student = result.student_input
    if student is None:
        return result
    redacted = StudentInputOutcome.model_validate(
        student.model_dump()
        | {
            "text": None,
            "step_id": None if student.step_id in removed else student.step_id,
            "observation_ids": [i for i in student.observation_ids if i not in removed],
            "assessment_id": None if student.assessment_id in removed else student.assessment_id,
            "verification": None,
            "reasoning_assessment": None,
            "explanation_judgment": None,
            "eligibility": [n for n in student.eligibility if n.observation_id not in removed],
        }
    )
    return result.model_copy(update={"student_input": redacted})


def settle_turns(repo: ScopedRepository, removed: set[str], now: datetime, tally: Tally) -> None:
    """Invalidate pending turns and drop cached turn content that depended on removed sources.

    Every pending turn is superseded, since its plan and provider context were built from
    evidence that has since changed. Superseded turns cannot commit tutor text, hints,
    drawings or memory (the coordinator replays a non-pending turn unchanged).
    """
    rows = list(
        repo.db.execute(
            select(TutorTurnRow)
            .where(TutorTurnRow.learner_id == repo.learner_id)
            .order_by(TutorTurnRow.created_at, TutorTurnRow.id)
        ).scalars()
    )
    invalidated_sessions: set[str] = set()
    for row in rows:
        content = {k: v for k, v in row.result.items() if k != _CONTEXT_KEY}
        references = bool(removed & (_string_leaves(content) | _string_leaves(row.plan)))
        if row.status == "pending":
            result = TutorTurnResult.model_validate(row.result)
            if references:
                result = _redact(result, removed)
                row.plan = {}
            result = result.model_copy(
                update={
                    "status": "superseded",
                    "completed_at": now,
                    "rejections": [*result.rejections, SOURCE_CHANGED],
                }
            )
            row.status = "superseded"
            row.completed_at = now
            row.result = result.model_dump(mode="json")
            tally.pending_turns_invalidated.append(row.id)
            invalidated_sessions.add(row.session_id)
        elif references:
            tally.turns_deleted.append(row.id)
            repo.db.delete(row)
        elif removed & _string_leaves(row.result.get(_CONTEXT_KEY, [])):
            row.result = row.result | {
                _CONTEXT_KEY: [i for i in row.result[_CONTEXT_KEY] if i not in removed]
            }
    for session_id in sorted(invalidated_sessions):
        bump_epoch(repo, session_id)
    INFLIGHT.cancel(tally.pending_turns_invalidated, "source_changed")
    repo.db.flush()


def recompute_mastery(repo: ScopedRepository, now: datetime, tally: Tally) -> None:
    """Replay the remaining raw evidence for each parameter version with derived rows."""
    db = repo.db
    versions = set(
        db.execute(
            select(MasteryEstimateRow.parameter_version).where(
                MasteryEstimateRow.learner_id == repo.learner_id
            )
        ).scalars()
    )
    versions |= set(
        db.execute(
            select(BKTCountedOpportunityRow.parameter_version).where(
                BKTCountedOpportunityRow.learner_id == repo.learner_id
            )
        ).scalars()
    )
    versions.add(DEFAULT_PARAMETERS.parameter_version)
    for version in sorted(versions):
        replay_learner(db, repo.learner_id, now, version)
        tally.recomputed_parameter_versions.append(version)
