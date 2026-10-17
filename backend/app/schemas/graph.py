"""Personal evidence links and graph-context contracts.

Evidence links connect one learner's observation to one of that learner's tentative
hypotheses with an explicit polarity. They live in their own table and never describe
concept-to-concept relationships, so personal evidence cannot become a curriculum
prerequisite.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    Confidence,
    ContractModel,
    EntityId,
    EvidenceKind,
    Provenance,
    ShortText,
    UtcDatetime,
)
from app.schemas.evidence import HypothesisStatus, ObservationSource

EvidencePolarity = Literal["supports", "contradicts"]
EVIDENCE_POLARITY_VALUES: tuple[EvidencePolarity, ...] = ("supports", "contradicts")
NodeRelation = Literal["target", "prerequisite", "dependent"]

MAX_CONTEXT_HOPS = 4
MAX_CONTEXT_NODES = 25
MAX_CONTEXT_HYPOTHESES = 10
MAX_CONTEXT_EVIDENCE = 20


class EvidenceLink(ContractModel):
    """``observation_id`` supports or contradicts ``hypothesis_id`` for one learner."""

    schema_version: Literal["evidence-link.v1"] = "evidence-link.v1"
    id: EntityId
    learner_id: EntityId
    hypothesis_id: EntityId
    observation_id: EntityId
    polarity: EvidencePolarity
    # How strongly this observation bears on the hypothesis; not a probability of truth.
    strength: Confidence
    rationale: ShortText
    provenance: Provenance
    created_at: UtcDatetime


class GraphContextBounds(ContractModel):
    """Budget for one context selection. Every list in the result honors these limits."""

    schema_version: Literal["graph-context-bounds.v1"] = "graph-context-bounds.v1"
    max_hops: Annotated[int, Field(ge=0, le=MAX_CONTEXT_HOPS)] = 2
    max_nodes: Annotated[int, Field(ge=1, le=MAX_CONTEXT_NODES)] = 8
    max_hypotheses: Annotated[int, Field(ge=0, le=MAX_CONTEXT_HYPOTHESES)] = 3
    max_evidence: Annotated[int, Field(ge=0, le=MAX_CONTEXT_EVIDENCE)] = 6
    # None means no age cutoff; recency still orders evidence within the budget.
    max_age_days: Annotated[int, Field(ge=1, le=3650)] | None = None


class ContextNode(ContractModel):
    concept_id: EntityId
    name: ShortText
    relation: NodeRelation
    hops: Annotated[int, Field(ge=0, le=MAX_CONTEXT_HOPS)]


class ContextCurriculumEdge(ContractModel):
    edge_id: EntityId
    prerequisite_id: EntityId
    concept_id: EntityId
    kind: Literal["curriculum_prerequisite"] = "curriculum_prerequisite"


class ContextHypothesis(ContractModel):
    hypothesis_id: EntityId
    concept_id: EntityId
    label: ShortText
    status: HypothesisStatus
    confidence: Confidence
    alternatives: list[ShortText]
    evidence_kind: Literal["inference"] = "inference"
    supporting_link_ids: list[EntityId]
    contradicting_link_ids: list[EntityId]


class ContextEvidence(ContractModel):
    link_id: EntityId
    hypothesis_id: EntityId
    polarity: EvidencePolarity
    strength: Confidence
    rationale: ShortText
    observation_id: EntityId
    source_type: ObservationSource
    source_id: EntityId
    evidence_kind: EvidenceKind
    concept_id: EntityId | None
    correct: bool | None
    assisted: bool
    confidence: Confidence
    provenance: Provenance
    observed_at: UtcDatetime


class OmittedCounts(ContractModel):
    """How many candidates the budget left out, so truncation is visible, not silent."""

    nodes: Annotated[int, Field(ge=0)]
    hypotheses: Annotated[int, Field(ge=0)]
    evidence: Annotated[int, Field(ge=0)]


class GraphContext(ContractModel):
    """A bounded, learner-scoped selection of curriculum and personal evidence.

    Curriculum nodes/edges are shared; hypotheses/evidence belong to ``learner_id`` only.
    ``source_ids`` lists every hypothesis, observation and underlying record that informed it.
    """

    schema_version: Literal["graph-context.v1"] = "graph-context.v1"
    selector: Literal["deterministic-graph-context.v1"] = "deterministic-graph-context.v1"
    learner_id: EntityId
    target_concept_id: EntityId
    generated_at: UtcDatetime
    bounds: GraphContextBounds
    nodes: list[ContextNode]
    curriculum_edges: list[ContextCurriculumEdge]
    hypotheses: list[ContextHypothesis]
    evidence: list[ContextEvidence]
    source_ids: list[EntityId]
    omitted: OmittedCounts
