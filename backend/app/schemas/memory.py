"""Six-layer memory view and the contract for provider-proposed memory updates.

Layers stay separate: raw evidence, derived beliefs, editable preferences, temporary session
context, source-linked episodic notes and persona configuration. A provider may only
*propose* a new session-context entry or episodic note, or flag an own note for review.
Nothing in a proposal can name a table, overwrite evidence, preferences, persona or
curriculum, or address another learner; such payloads fail this schema outright.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    Confidence,
    ContractModel,
    EntityId,
    ShortText,
    UtcDatetime,
)
from app.schemas.evidence import MasteryEstimate, MisconceptionHypothesis, Observation
from app.schemas.learner import MemoryEntry, Preference, TutorConfiguration

MAX_PROPOSALS_PER_TURN = 5
MAX_PROPOSAL_SOURCES = 8
MAX_LAYER_ITEMS = 50
# Provider inferences never claim near-certainty about a person.
MAX_INFERENCE_CONFIDENCE = 0.8

ProposalText = Annotated[str, Field(min_length=1, max_length=300)]
ProposalSources = Annotated[
    list[EntityId], Field(min_length=1, max_length=MAX_PROPOSAL_SOURCES)
]


class CreateSessionContextProposal(ContractModel):
    """Temporary context for the current session only, e.g. "said they are tired today"."""

    schema_version: Literal["memory-update-proposal.v1"] = "memory-update-proposal.v1"
    operation: Literal["create_session_context"]
    learner_id: EntityId
    session_id: EntityId
    content: ProposalText
    evidence_kind: Literal["self_report", "inference"]
    confidence: Confidence
    source_ids: ProposalSources
    expires_at: UtcDatetime


class CreateEpisodicNoteProposal(ContractModel):
    """A durable, reviewable note that must cite the learner's own records."""

    schema_version: Literal["memory-update-proposal.v1"] = "memory-update-proposal.v1"
    operation: Literal["create_episodic_note"]
    learner_id: EntityId
    session_id: EntityId | None = None
    content: ProposalText
    evidence_kind: Literal["self_report", "inference"]
    confidence: Confidence
    source_ids: ProposalSources
    review_at: UtcDatetime
    expires_at: UtcDatetime | None = None


class FlagNoteForReviewProposal(ContractModel):
    """Ask for an own episodic note to be reviewed. It cannot change the note's content."""

    schema_version: Literal["memory-update-proposal.v1"] = "memory-update-proposal.v1"
    operation: Literal["flag_note_for_review"]
    learner_id: EntityId
    memory_id: EntityId
    reason: ShortText
    source_ids: ProposalSources


MemoryUpdateProposal = Annotated[
    CreateSessionContextProposal | CreateEpisodicNoteProposal | FlagNoteForReviewProposal,
    Field(discriminator="operation"),
]

RejectionCode = Literal[
    "schema_invalid",
    "too_many_proposals",
    "foreign_learner",
    "invalid_scope",
    "invalid_expiry",
    "unknown_source",
    "source_not_in_context",
    "unsupported_evidence_kind",
    "confidence_too_high",
    "unknown_target",
    "duplicate_proposal",
    "conflicting_replay",
]


class ProposalRejection(ContractModel):
    index: Annotated[int, Field(ge=0)]
    code: RejectionCode
    message: ShortText


class MemoryUpdateResult(ContractModel):
    """Outcome of a whole batch. Any rejection means nothing in the batch was written."""

    schema_version: Literal["memory-update-result.v1"] = "memory-update-result.v1"
    status: Literal["applied", "rejected", "empty"]
    applied_ids: list[EntityId]
    replayed_ids: list[EntityId]
    rejections: list[ProposalRejection]


class SessionContextLayer(ContractModel):
    current_session_id: EntityId | None
    active: list[MemoryEntry]
    # Earlier temporary context is not carried forward; the tutor asks again instead.
    expired_count: Annotated[int, Field(ge=0)]
    recheck_needed: bool


class EpisodicNote(ContractModel):
    entry: MemoryEntry
    review_due: bool


class MemoryLayers(ContractModel):
    """A bounded, learner-scoped snapshot that keeps each layer separately identifiable."""

    schema_version: Literal["memory-layers.v1"] = "memory-layers.v1"
    learner_id: EntityId
    generated_at: UtcDatetime
    limit: Annotated[int, Field(ge=1, le=MAX_LAYER_ITEMS)]
    raw_evidence: list[Observation]
    derived_hypotheses: list[MisconceptionHypothesis]
    derived_estimates: list[MasteryEstimate]
    preferences: list[Preference]
    session_context: SessionContextLayer
    episodic_notes: list[EpisodicNote]
    persona: TutorConfiguration | None
