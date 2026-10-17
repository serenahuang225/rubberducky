"""Learner identity, session, preference, persona configuration and memory contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.common import (
    Confidence,
    ContractModel,
    EntityId,
    EvidenceKind,
    LongText,
    Provenance,
    ShortText,
    SourceIds,
    UtcDatetime,
)

SessionStatus = Literal["active", "ended", "expired"]
Appearance = Literal["animal", "older_adult", "younger_adult"]
Personality = Literal["gentle", "matter_of_fact", "playful", "mildly_sassy"]
ComfortOverride = Literal["none", "neutral_supportive", "reduced_sass"]
MemoryLayer = Literal["episodic_note", "session_context"]
MemoryStatus = Literal["active", "needs_review", "corrected", "expired", "deleted"]
# Who wrote a memory entry: the learner, a validated tutor proposal, or the system/seed.
MemoryOrigin = Literal["learner", "tutor_proposal", "system"]
MEMORY_ORIGIN_VALUES: tuple[MemoryOrigin, ...] = ("learner", "tutor_proposal", "system")
# Preferences are edited only by the learner or a local operator, never by a provider.
PreferenceEditor = Literal["learner", "operator"]
PREFERENCE_EDITOR_VALUES: tuple[PreferenceEditor, ...] = ("learner", "operator")
PreferenceKey = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
PreferenceValue = Annotated[str, Field(max_length=200)] | bool | int | FiniteFloat | None


class Learner(ContractModel):
    schema_version: Literal["learner.v1"] = "learner.v1"
    id: EntityId
    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    # Every identity in this prototype is a labeled fictional demo learner.
    is_fictional: bool
    provenance: Provenance
    created_at: UtcDatetime


class Session(ContractModel):
    schema_version: Literal["session.v1"] = "session.v1"
    id: EntityId
    learner_id: EntityId
    status: SessionStatus
    goal: ShortText | None = None
    revision: Annotated[int, Field(ge=0)] = 0
    provenance: Provenance
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at precedes started_at")
        return self


class Preference(ContractModel):
    schema_version: Literal["preference.v1"] = "preference.v1"
    id: EntityId
    learner_id: EntityId
    key: PreferenceKey
    value: PreferenceValue
    provenance: Provenance
    updated_by: PreferenceEditor = "learner"
    updated_at: UtcDatetime


class TutorConfiguration(ContractModel):
    schema_version: Literal["tutor-configuration.v1"] = "tutor-configuration.v1"
    id: EntityId
    learner_id: EntityId
    appearance: Appearance
    personality: Personality
    comfort_override: ComfortOverride = "none"
    provenance: Provenance
    chosen_at: UtcDatetime
    last_changed_at: UtcDatetime


class MemoryEntry(ContractModel):
    """A source-linked note. Inferred notes keep their evidence kind and confidence."""

    schema_version: Literal["memory-entry.v1"] = "memory-entry.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId | None = None
    layer: MemoryLayer
    content: LongText
    evidence_kind: EvidenceKind
    confidence: Confidence
    source_ids: Annotated[SourceIds, Field(min_length=1)]
    status: MemoryStatus = "active"
    review_at: UtcDatetime | None = None
    expires_at: UtcDatetime | None = None
    origin: MemoryOrigin = "system"
    # The tutor turn whose validated proposal created this entry, if any.
    turn_id: EntityId | None = None
    # A correction points at the entry it replaces; the original keeps status "corrected".
    supersedes_id: EntityId | None = None
    provenance: Provenance
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _session_context_is_scoped(self) -> Self:
        if self.layer == "session_context" and self.session_id is None:
            raise ValueError("session_context memory requires a session_id")
        return self


class SceneObject(ContractModel):
    """Durable logical-coordinate scene object. Payload geometry is validated by the scene layer."""

    schema_version: Literal["scene-object.v1"] = "scene-object.v1"
    id: EntityId
    learner_id: EntityId
    session_id: EntityId
    author_role: Literal["student", "tutor"]
    semantic_role: Annotated[str, Field(min_length=1, max_length=40)]
    kind: Annotated[str, Field(min_length=1, max_length=40)]
    payload: dict[str, object]
    teaching_step_id: EntityId | None = None
    provenance: Provenance
    created_at: UtcDatetime
    deleted_at: UtcDatetime | None = None
