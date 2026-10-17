"""Contracts for the bounded tutor context sent to a language-model provider.

The context is a selection, never a lifetime transcript. Every item keeps its source IDs,
evidence polarity and epistemic status (curriculum fact, observed or verified work,
self-report, inference, derived estimate or learner setting), including after its free text
is summarized away to fit the budget. What the budget left out is counted, not hidden.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId, UtcDatetime
from app.schemas.graph import EvidencePolarity, GraphContextBounds

EpistemicStatus = Literal[
    "curriculum",
    "observed",
    "verified",
    "self_report",
    "inference",
    "derived_estimate",
    "learner_setting",
]
ContextItemKind = Literal[
    "target_concept",
    "related_concept",
    "prerequisite_edge",
    "hypothesis",
    "evidence",
    "recent_observation",
    "mastery_estimate",
    "session_context",
    "episodic_note",
    "preference",
    "persona",
]
OmissionReason = Literal[
    "selection_bound",
    "budget",
    "outside_window",
    "not_current_session",
    "review_due",
]
Sufficiency = Literal["sufficient", "limited", "insufficient"]
FactValue = str | int | float | bool | None | list[str]

MAX_CONTEXT_CHARS = 32_000
MAX_CONTEXT_TOKENS = 16_000


def _default_graph_bounds() -> GraphContextBounds:
    return GraphContextBounds(max_age_days=180)


class ContextBudget(ContractModel):
    """Hard selection and size limits for one assembled context.

    Defaults are the production settings; tests pass much smaller budgets.
    """

    schema_version: Literal["context-budget.v1"] = "context-budget.v1"
    graph: GraphContextBounds = Field(default_factory=_default_graph_bounds)
    max_recent_observations: Annotated[int, Field(ge=0, le=20)] = 6
    recent_window_days: Annotated[int, Field(ge=1, le=365)] = 60
    max_session_context: Annotated[int, Field(ge=0, le=5)] = 3
    max_notes: Annotated[int, Field(ge=0, le=10)] = 4
    max_preferences: Annotated[int, Field(ge=0, le=20)] = 8
    max_serialized_chars: Annotated[int, Field(ge=1, le=MAX_CONTEXT_CHARS)] = 16_000
    max_context_tokens: Annotated[int, Field(ge=1, le=MAX_CONTEXT_TOKENS)] = 12_000


class ContextItem(ContractModel):
    ref: EntityId
    kind: ContextItemKind
    status: EpistemicStatus
    source_ids: list[EntityId] = Field(default_factory=list, max_length=20)
    polarity: EvidencePolarity | None = None
    hypothesis_id: EntityId | None = None
    concept_id: EntityId | None = None
    at: UtcDatetime | None = None
    facts: dict[str, FactValue] = Field(default_factory=dict)
    # Free text (rationale, note content). Dropped first when the budget is tight.
    text: str | None = None
    summarized: bool = False


class OmissionCount(ContractModel):
    kind: ContextItemKind
    reason: OmissionReason
    count: Annotated[int, Field(ge=1)]


class ContextPayload(ContractModel):
    """Exactly what is serialized into the provider request."""

    schema_version: Literal["tutor-context-payload.v1"] = "tutor-context-payload.v1"
    target_concept_id: EntityId
    session_id: EntityId | None
    sufficiency: Sufficiency
    gaps: list[str]
    # Earlier temporary context exists but is not carried forward; ask the learner again.
    session_context_recheck: bool
    items: list[ContextItem]
    omitted: list[OmissionCount]


class TutorContext(ContractModel):
    """The payload plus how it was measured and what may be cited from it."""

    schema_version: Literal["tutor-context.v1"] = "tutor-context.v1"
    selector: Literal["bounded-tutor-context.v1"] = "bounded-tutor-context.v1"
    learner_id: EntityId
    generated_at: UtcDatetime
    budget: ContextBudget
    effective_max_chars: Annotated[int, Field(ge=0)]
    effective_max_tokens: Annotated[int, Field(ge=0)]
    payload: ContextPayload
    serialized: str
    serialized_chars: Annotated[int, Field(ge=0)]
    serialized_bytes: Annotated[int, Field(ge=0)]
    token_count: Annotated[int, Field(ge=0)]
    token_counter: str
    within_budget: bool
    citable_ids: list[EntityId]
    # IDs selected by the graph/memory bounds but removed to meet the size budget.
    budget_omitted_ids: list[EntityId]
