"""Validate and apply provider-proposed memory updates for one scoped learner.

A provider draft only *proposes*; this module decides. The whole batch is validated against
the authenticated learner, the current session, the sources actually shown to the provider
and fixed expiry windows before anything is written. If any proposal is rejected, nothing
from the batch is written. Proposals created under a turn ID get deterministic entry IDs, so
retrying the same turn replays rather than duplicates.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from app.db.models import (
    AssessmentRow,
    AttemptRow,
    Base,
    HintRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    StepRow,
)
from app.db.repositories import NotInScopeError, ScopedRepository
from app.learner.pairing import new_id
from app.schemas import MemoryEntry
from app.schemas.memory import (
    MAX_INFERENCE_CONFIDENCE,
    MAX_PROPOSALS_PER_TURN,
    CreateEpisodicNoteProposal,
    CreateSessionContextProposal,
    FlagNoteForReviewProposal,
    MemoryUpdateProposal,
    MemoryUpdateResult,
    ProposalRejection,
    RejectionCode,
)

SESSION_CONTEXT_MAX_TTL = timedelta(hours=12)
NOTE_MIN_REVIEW_DELAY = timedelta(days=1)
NOTE_MAX_REVIEW_DELAY = timedelta(days=180)
NOTE_MAX_LIFETIME = timedelta(days=365)

_ADAPTER: TypeAdapter[MemoryUpdateProposal] = TypeAdapter(MemoryUpdateProposal)
_NAMESPACE = uuid.UUID("3c8a8f9e-5a3b-4f0c-8d1e-9b7f2a6c4e11")
# Records a memory proposal may cite. Curriculum, preferences and persona are not evidence.
_SOURCE_TABLES: tuple[type[Base], ...] = (
    ObservationRow,
    StepRow,
    HintRow,
    AssessmentRow,
    AttemptRow,
    MisconceptionHypothesisRow,
    MemoryEntryRow,
)


@dataclass(frozen=True)
class ProposalScope:
    """Where a batch of proposals came from.

    ``citable_source_ids`` is the set of IDs present in the context actually sent to the
    provider. When given, citing anything else (an omitted, deleted or invented record) is
    rejected even if the learner owns it.
    """

    session_id: str | None
    turn_id: str | None = None
    citable_source_ids: frozenset[str] | None = None


class _RejectedError(Exception):
    def __init__(self, code: RejectionCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _Create:
    index: int
    entry: MemoryEntry


@dataclass(frozen=True)
class _Flag:
    index: int
    memory_id: str


def proposal_entry_id(learner_id: str, turn_id: str, index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{learner_id}|{turn_id}|{index}"))


def _owned_sources(repo: ScopedRepository, ids: set[str]) -> dict[str, Base]:
    found: dict[str, Base] = {}
    for model in _SOURCE_TABLES:
        rows = repo.db.execute(
            select(model).where(
                model.id.in_(ids),  # type: ignore[attr-defined]
                model.learner_id == repo.learner_id,  # type: ignore[attr-defined]
            )
        ).scalars()
        for row in rows:
            if isinstance(row, MisconceptionHypothesisRow) and row.status == "retracted":
                continue
            if isinstance(row, MemoryEntryRow) and row.status != "active":
                continue
            found[row.id] = row  # type: ignore[attr-defined]
    return found


def _check_sources(
    repo: ScopedRepository,
    source_ids: list[str],
    scope: ProposalScope,
    evidence_kind: str | None,
) -> None:
    if len(set(source_ids)) != len(source_ids):
        raise _RejectedError("schema_invalid", "source_ids contains duplicates")
    if scope.citable_source_ids is not None:
        missing = [s for s in source_ids if s not in scope.citable_source_ids]
        if missing:
            raise _RejectedError(
                "source_not_in_context", f"{len(missing)} cited source(s) were not in context"
            )
    owned = _owned_sources(repo, set(source_ids))
    # Foreign, deleted and invented IDs get the same answer, so there is no existence oracle.
    unknown = [s for s in source_ids if s not in owned]
    if unknown:
        raise _RejectedError("unknown_source", f"{len(unknown)} cited source(s) are not available")
    if evidence_kind == "self_report" and not any(
        isinstance(row, ObservationRow) and row.evidence_kind == "self_report"
        for row in owned.values()
    ):
        raise _RejectedError(
            "unsupported_evidence_kind", "a self_report needs a cited self-report observation"
        )


def _check_confidence(evidence_kind: str, confidence: float) -> None:
    if evidence_kind == "inference" and confidence > MAX_INFERENCE_CONFIDENCE:
        raise _RejectedError(
            "confidence_too_high", f"inference confidence must be <= {MAX_INFERENCE_CONFIDENCE}"
        )


def _require_active_session(repo: ScopedRepository, session_id: str) -> None:
    try:
        session = repo.require_session(session_id)
    except NotInScopeError as error:
        raise _RejectedError("invalid_scope", "session is not available") from error
    if session.status != "active":
        raise _RejectedError("invalid_scope", "session is not active")


def _entry_id(repo: ScopedRepository, scope: ProposalScope, index: int) -> str:
    if scope.turn_id is None:
        return new_id()
    return proposal_entry_id(repo.learner_id, scope.turn_id, index)


def _session_context(
    repo: ScopedRepository,
    proposal: CreateSessionContextProposal,
    scope: ProposalScope,
    index: int,
    now: datetime,
) -> _Create:
    if scope.session_id is None or proposal.session_id != scope.session_id:
        raise _RejectedError("invalid_scope", "session context must target the current session")
    _require_active_session(repo, proposal.session_id)
    if not now < proposal.expires_at <= now + SESSION_CONTEXT_MAX_TTL:
        raise _RejectedError("invalid_expiry", "session context must expire within 12 hours")
    _check_confidence(proposal.evidence_kind, proposal.confidence)
    _check_sources(repo, proposal.source_ids, scope, proposal.evidence_kind)
    return _Create(
        index,
        MemoryEntry(
            id=_entry_id(repo, scope, index),
            learner_id=repo.learner_id,
            session_id=proposal.session_id,
            layer="session_context",
            content=proposal.content,
            evidence_kind=proposal.evidence_kind,
            confidence=proposal.confidence,
            source_ids=proposal.source_ids,
            status="active",
            expires_at=proposal.expires_at,
            origin="tutor_proposal",
            turn_id=scope.turn_id,
            provenance="submitted",
            created_at=now,
            updated_at=now,
        ),
    )


def _episodic_note(
    repo: ScopedRepository,
    proposal: CreateEpisodicNoteProposal,
    scope: ProposalScope,
    index: int,
    now: datetime,
) -> _Create:
    if proposal.session_id is not None:
        if proposal.session_id != scope.session_id:
            raise _RejectedError("invalid_scope", "a note may only reference the current session")
        _require_active_session(repo, proposal.session_id)
    if not now + NOTE_MIN_REVIEW_DELAY <= proposal.review_at <= now + NOTE_MAX_REVIEW_DELAY:
        raise _RejectedError("invalid_expiry", "review_at must be between 1 and 180 days ahead")
    if proposal.expires_at is not None and not (
        proposal.review_at < proposal.expires_at <= now + NOTE_MAX_LIFETIME
    ):
        raise _RejectedError("invalid_expiry", "expires_at must follow review_at, within 365 days")
    _check_confidence(proposal.evidence_kind, proposal.confidence)
    _check_sources(repo, proposal.source_ids, scope, proposal.evidence_kind)
    return _Create(
        index,
        MemoryEntry(
            id=_entry_id(repo, scope, index),
            learner_id=repo.learner_id,
            session_id=proposal.session_id,
            layer="episodic_note",
            content=proposal.content,
            evidence_kind=proposal.evidence_kind,
            confidence=proposal.confidence,
            source_ids=proposal.source_ids,
            status="active",
            review_at=proposal.review_at,
            expires_at=proposal.expires_at,
            origin="tutor_proposal",
            turn_id=scope.turn_id,
            provenance="submitted",
            created_at=now,
            updated_at=now,
        ),
    )


def _flag(
    repo: ScopedRepository, proposal: FlagNoteForReviewProposal, scope: ProposalScope, index: int
) -> _Flag:
    row = repo.db.execute(
        select(MemoryEntryRow).where(
            MemoryEntryRow.id == proposal.memory_id,
            MemoryEntryRow.learner_id == repo.learner_id,
        )
    ).scalar_one_or_none()
    if (
        row is None
        or row.layer != "episodic_note"
        or row.status not in ("active", "needs_review")
    ):
        raise _RejectedError("unknown_target", "no reviewable note with that ID")
    if scope.citable_source_ids is not None and proposal.memory_id not in scope.citable_source_ids:
        raise _RejectedError("source_not_in_context", "the note was not in context")
    _check_sources(repo, proposal.source_ids, scope, None)
    return _Flag(index, proposal.memory_id)


_REPLAY_FIELDS = (
    "layer",
    "session_id",
    "content",
    "evidence_kind",
    "confidence",
    "source_ids",
    "review_at",
    "expires_at",
    "turn_id",
)


def _replay_status(repo: ScopedRepository, entry: MemoryEntry) -> str:
    """"new", "replay" (identical entry already stored) or "conflict"."""
    row = repo.db.get(MemoryEntryRow, entry.id)
    if row is None:
        return "new"
    if row.learner_id != repo.learner_id:
        return "conflict"
    stored = MemoryEntry.model_validate(row)
    same = all(getattr(stored, f) == getattr(entry, f) for f in _REPLAY_FIELDS)
    return "replay" if same else "conflict"


def parse_proposals(
    raw: Sequence[object],
) -> tuple[list[tuple[int, MemoryUpdateProposal]], list[ProposalRejection]]:
    parsed: list[tuple[int, MemoryUpdateProposal]] = []
    rejections: list[ProposalRejection] = []
    for index, item in enumerate(raw):
        payload = item.model_dump() if hasattr(item, "model_dump") else item
        try:
            parsed.append((index, _ADAPTER.validate_python(payload)))
        except ValidationError as error:
            first = error.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or "proposal"
            rejections.append(
                ProposalRejection(
                    index=index,
                    code="schema_invalid",
                    message=f"{where}: {first['msg']}"[:200],
                )
            )
    return parsed, rejections


def apply_memory_updates(
    repo: ScopedRepository,
    raw: Sequence[object],
    scope: ProposalScope,
    now: datetime,
) -> MemoryUpdateResult:
    """Validate the whole batch, then write it in the caller's transaction (no commit)."""
    if not raw:
        return MemoryUpdateResult(status="empty", applied_ids=[], replayed_ids=[], rejections=[])
    if len(raw) > MAX_PROPOSALS_PER_TURN:
        return MemoryUpdateResult(
            status="rejected",
            applied_ids=[],
            replayed_ids=[],
            rejections=[
                ProposalRejection(
                    index=MAX_PROPOSALS_PER_TURN,
                    code="too_many_proposals",
                    message=f"at most {MAX_PROPOSALS_PER_TURN} proposals per turn",
                )
            ],
        )
    parsed, rejections = parse_proposals(raw)
    planned: list[_Create | _Flag] = []
    seen: set[str] = set()
    for index, proposal in parsed:
        try:
            if proposal.learner_id != repo.learner_id:
                raise _RejectedError("foreign_learner", "proposal names a different learner")
            key = json.dumps(proposal.model_dump(mode="json"), sort_keys=True)
            if key in seen:
                raise _RejectedError("duplicate_proposal", "same proposal earlier in the batch")
            seen.add(key)
            if isinstance(proposal, CreateSessionContextProposal):
                planned.append(_session_context(repo, proposal, scope, index, now))
            elif isinstance(proposal, CreateEpisodicNoteProposal):
                planned.append(_episodic_note(repo, proposal, scope, index, now))
            else:
                planned.append(_flag(repo, proposal, scope, index))
        except _RejectedError as rejection:
            rejections.append(
                ProposalRejection(index=index, code=rejection.code, message=rejection.message)
            )

    applied: list[str] = []
    replayed: list[str] = []
    writes: list[_Create | _Flag] = []
    for item in planned:
        if isinstance(item, _Flag):
            writes.append(item)
            continue
        status = _replay_status(repo, item.entry)
        if status == "conflict":
            rejections.append(
                ProposalRejection(
                    index=item.index,
                    code="conflicting_replay",
                    message="this turn already stored a different proposal",
                )
            )
        elif status == "replay":
            replayed.append(item.entry.id)
        else:
            writes.append(item)

    if rejections:
        return MemoryUpdateResult(
            status="rejected",
            applied_ids=[],
            replayed_ids=[],
            rejections=sorted(rejections, key=lambda r: r.index),
        )
    for item in writes:
        if isinstance(item, _Create):
            repo.db.add(MemoryEntryRow(**item.entry.model_dump()))
            applied.append(item.entry.id)
        else:
            row = repo.db.get(MemoryEntryRow, item.memory_id)
            if row is not None and row.status == "active":
                row.status = "needs_review"
                row.updated_at = now
                applied.append(item.memory_id)
            else:
                replayed.append(item.memory_id)
    repo.db.flush()
    return MemoryUpdateResult(
        status="applied", applied_ids=applied, replayed_ids=replayed, rejections=[]
    )
