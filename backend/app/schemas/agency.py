"""Contracts for the learner's private memory view, corrections, deletions and removals.

Nothing here carries hidden reasoning. A receipt lists what changed so a client can show the
learner exactly which beliefs, notes, turns and estimates were invalidated or recomputed.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    Confidence,
    ContractModel,
    EntityId,
    EvidenceKind,
    ShortText,
    UtcDatetime,
)
from app.schemas.evidence import MasteryEstimate

MAX_INSPECTION_ITEMS = 50
MAX_NOTE_CORRECTION_CHARS = 300

ItemKind = Literal["evidence", "hypothesis", "note", "session_context", "estimate"]
MemoryItemLayer = Literal[
    "raw_evidence", "derived_belief", "episodic_note", "session_context", "derived_estimate"
]
ItemState = Literal[
    "current", "needs_review", "corrected", "retracted", "superseded", "expired", "uncalibrated"
]
SourceKind = Literal[
    "step",
    "assessment",
    "hint",
    "observation",
    "hypothesis",
    "memory_entry",
    "session",
    "turn",
    "unknown",
]
Qualitative = Literal["low", "moderate", "high", "not_applicable"]


class SourceExplanation(ContractModel):
    """One cited source, explained in plain language, with its excerpt when it still exists."""

    id: EntityId
    kind: SourceKind
    label: Annotated[str, Field(max_length=200)]
    at: UtcDatetime | None = None
    excerpt: Annotated[str, Field(max_length=200)] | None = None
    # False when the source was deleted or never existed for this learner.
    available: bool = True


class Uncertainty(ContractModel):
    qualitative: Qualitative
    confidence: Confidence | None = None
    explanation: Annotated[str, Field(max_length=240)]


class CorrectionInfo(ContractModel):
    """What the learner changed. The original value is preserved, never presented as measured."""

    original: Annotated[str, Field(max_length=500)]
    current: Annotated[str, Field(max_length=500)]
    corrected_at: UtcDatetime
    corrected_by: Literal["learner"] = "learner"


class ItemAction(ContractModel):
    action: Literal["correct", "delete"]
    method: Literal["POST", "DELETE"]
    path: Annotated[str, Field(max_length=200)]


class MemoryItem(ContractModel):
    kind: ItemKind
    id: EntityId
    layer: MemoryItemLayer
    title: ShortText
    summary: Annotated[str, Field(max_length=500)]
    epistemic_status: Literal[
        "observed", "verified", "self_report", "inference", "derived_estimate"
    ]
    evidence_kind: EvidenceKind | None = None
    state: ItemState
    uncertainty: Uncertainty
    why_it_matters: Annotated[str, Field(max_length=300)]
    provenance: Literal["fictional_seed", "submitted"]
    origin: Literal["learner", "tutor_proposal", "system", "measured"]
    sources: list[SourceExplanation]
    correction: CorrectionInfo | None = None
    supersedes_id: EntityId | None = None
    at: UtcDatetime
    actions: list[ItemAction]


class MemoryInspection(ContractModel):
    """The private view: what is remembered, where it came from, how sure it is, why it matters."""

    schema_version: Literal["memory-inspection.v1"] = "memory-inspection.v1"
    learner_id: EntityId
    generated_at: UtcDatetime
    limit: Annotated[int, Field(ge=1, le=MAX_INSPECTION_ITEMS)]
    items: list[MemoryItem]
    notice: str = (
        "This is your private memory view. Estimates are uncalibrated guesses from limited "
        "evidence; you can correct or delete anything here."
    )


class DerivedEffects(ContractModel):
    """Everything derived from the changed source that was invalidated or recomputed."""

    schema_version: Literal["derived-effects.v1"] = "derived-effects.v1"
    hypotheses_retracted: list[EntityId] = Field(default_factory=list)
    hypotheses_deleted: list[EntityId] = Field(default_factory=list)
    notes_flagged_for_review: list[EntityId] = Field(default_factory=list)
    notes_deleted: list[EntityId] = Field(default_factory=list)
    turns_deleted: list[EntityId] = Field(default_factory=list)
    pending_turns_invalidated: list[EntityId] = Field(default_factory=list)
    recomputed_parameter_versions: list[str] = Field(default_factory=list)
    mastery_estimates: list[MasteryEstimate] = Field(default_factory=list)


class CorrectEvidenceRequest(ContractModel):
    correct: bool


class CorrectNoteRequest(ContractModel):
    content: Annotated[str, Field(min_length=1, max_length=MAX_NOTE_CORRECTION_CHARS)]


class CorrectionReceipt(ContractModel):
    schema_version: Literal["memory-correction.v1"] = "memory-correction.v1"
    kind: ItemKind
    record_id: EntityId
    # False when the correction matched the current value and nothing was changed.
    changed: bool
    replacement_id: EntityId | None = None
    original: str | None = None
    current: str | None = None
    effects: DerivedEffects


class DeletionReceipt(ContractModel):
    schema_version: Literal["memory-deletion.v1"] = "memory-deletion.v1"
    kind: ItemKind
    record_id: EntityId
    deleted_ids: list[EntityId]
    tombstones_written: Annotated[int, Field(ge=0)]
    effects: DerivedEffects
    notice: str = "Removed from the active local store; no deleted text is retained."


class RemovalReceipt(ContractModel):
    """Before/after inventory for a session or whole-profile removal."""

    schema_version: Literal["removal-receipt.v1"] = "removal-receipt.v1"
    scope: Literal["session", "profile"]
    record_id: EntityId
    before: dict[str, int]
    after: dict[str, int]
    credentials_revoked: Annotated[int, Field(ge=0)] = 0
    tombstones_written: Annotated[int, Field(ge=0)]
    effects: DerivedEffects
    notice: str = (
        "Removed from the active local store. This is not secure disk, backup or vendor "
        "erasure, and the shared curriculum and other learners are untouched."
    )
