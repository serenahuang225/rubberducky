"""Bounded graph context: curriculum neighborhood plus recent support/contradiction.

Selection is deterministic and never calls a model. Curriculum nodes and edges come from the
shared DAG; hypotheses and evidence come only from the scoped learner's own records. Every
list is capped by :class:`GraphContextBounds`, and omitted counts are reported.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import zip_longest

from sqlalchemy import select

from app.db.models import EvidenceLinkRow, MisconceptionHypothesisRow, ObservationRow
from app.db.repositories import ScopedRepository
from app.graph.curriculum import CurriculumGraph, load_curriculum_graph
from app.schemas.graph import (
    ContextCurriculumEdge,
    ContextEvidence,
    ContextHypothesis,
    ContextNode,
    GraphContext,
    GraphContextBounds,
    NodeRelation,
    OmittedCounts,
)


def _select_nodes(
    graph: CurriculumGraph, concept_id: str, bounds: GraphContextBounds
) -> tuple[list[ContextNode], int]:
    prerequisites = graph.prerequisites(concept_id, bounds.max_hops)
    dependents = graph.dependents(concept_id, bounds.max_hops)
    candidates: list[tuple[int, int, str, NodeRelation]] = [(0, 0, concept_id, "target")]
    # Prerequisites rank ahead of dependents at equal distance: they explain current errors.
    candidates += [(hops, 1, cid, "prerequisite") for cid, hops in prerequisites.items()]
    candidates += [(hops, 2, cid, "dependent") for cid, hops in dependents.items()]
    candidates.sort()
    chosen = candidates[: bounds.max_nodes]
    nodes = [
        ContextNode(concept_id=cid, name=graph.name(cid), relation=relation, hops=hops)
        for hops, _, cid, relation in chosen
    ]
    return nodes, len(candidates) - len(chosen)


def _select_edges(graph: CurriculumGraph, node_ids: set[str]) -> list[ContextCurriculumEdge]:
    induced = graph.graph.subgraph(node_ids)
    return [
        ContextCurriculumEdge(
            edge_id=graph.edge_id(pre, post), prerequisite_id=pre, concept_id=post
        )
        for pre, post in sorted(induced.edges())
    ]


def _interleave_polarities(items: list[ContextEvidence]) -> Iterator[ContextEvidence]:
    """Alternate supports/contradicts, newest first, so a small budget keeps both sides."""
    supports = [item for item in items if item.polarity == "supports"]
    contradicts = [item for item in items if item.polarity == "contradicts"]
    if contradicts and (not supports or contradicts[0].observed_at > supports[0].observed_at):
        first, second = contradicts, supports
    else:
        first, second = supports, contradicts
    for pair in zip_longest(first, second):
        yield from (item for item in pair if item is not None)


def build_graph_context(
    repo: ScopedRepository,
    concept_id: str,
    now: datetime,
    bounds: GraphContextBounds | None = None,
) -> GraphContext:
    bounds = bounds or GraphContextBounds()
    graph = load_curriculum_graph(repo.db)
    nodes, omitted_nodes = _select_nodes(graph, concept_id, bounds)
    node_ids = {node.concept_id for node in nodes}

    hypothesis_rows = list(
        repo.db.execute(
            select(MisconceptionHypothesisRow)
            .where(
                MisconceptionHypothesisRow.learner_id == repo.learner_id,
                MisconceptionHypothesisRow.concept_id.in_(node_ids),
                MisconceptionHypothesisRow.status != "retracted",
            )
            .order_by(MisconceptionHypothesisRow.updated_at.desc(), MisconceptionHypothesisRow.id)
        ).scalars()
    )
    chosen_hypotheses = hypothesis_rows[: bounds.max_hypotheses]
    hypothesis_ids = [row.id for row in chosen_hypotheses]

    evidence_query = (
        select(EvidenceLinkRow, ObservationRow)
        .join(
            ObservationRow,
            (ObservationRow.id == EvidenceLinkRow.observation_id)
            & (ObservationRow.learner_id == EvidenceLinkRow.learner_id),
        )
        .where(
            EvidenceLinkRow.learner_id == repo.learner_id,
            EvidenceLinkRow.hypothesis_id.in_(hypothesis_ids),
            ObservationRow.observed_at <= now,
        )
        .order_by(ObservationRow.observed_at.desc(), EvidenceLinkRow.id)
    )
    if bounds.max_age_days is not None:
        evidence_query = evidence_query.where(
            ObservationRow.observed_at >= now - timedelta(days=bounds.max_age_days)
        )
    candidates = [
        ContextEvidence(
            link_id=link.id,
            hypothesis_id=link.hypothesis_id,
            polarity=link.polarity,  # type: ignore[arg-type]
            strength=link.strength,
            rationale=link.rationale,
            observation_id=obs.id,
            source_type=obs.source_type,  # type: ignore[arg-type]
            source_id=obs.source_id,
            evidence_kind=obs.evidence_kind,  # type: ignore[arg-type]
            concept_id=obs.concept_id,
            correct=obs.correct,
            assisted=obs.assisted,
            confidence=obs.confidence,
            provenance=obs.provenance,  # type: ignore[arg-type]
            observed_at=obs.observed_at,
        )
        for link, obs in repo.db.execute(evidence_query)
    ]
    evidence = list(_interleave_polarities(candidates))[: bounds.max_evidence]
    evidence.sort(key=lambda item: (item.observed_at, item.link_id), reverse=True)

    hypotheses = [
        ContextHypothesis(
            hypothesis_id=row.id,
            concept_id=row.concept_id,
            label=row.label,
            status=row.status,  # type: ignore[arg-type]
            confidence=row.confidence,
            alternatives=list(row.alternatives),
            supporting_link_ids=[
                e.link_id
                for e in evidence
                if e.hypothesis_id == row.id and e.polarity == "supports"
            ],
            contradicting_link_ids=[
                e.link_id
                for e in evidence
                if e.hypothesis_id == row.id and e.polarity == "contradicts"
            ],
        )
        for row in chosen_hypotheses
    ]

    source_ids: list[str] = []
    for value in [
        *(h.hypothesis_id for h in hypotheses),
        *(i for e in evidence for i in (e.link_id, e.observation_id, e.source_id)),
    ]:
        if value not in source_ids:
            source_ids.append(value)

    return GraphContext(
        learner_id=repo.learner_id,
        target_concept_id=concept_id,
        generated_at=now,
        bounds=bounds,
        nodes=nodes,
        curriculum_edges=_select_edges(graph, node_ids),
        hypotheses=hypotheses,
        evidence=evidence,
        source_ids=source_ids,
        omitted=OmittedCounts(
            nodes=omitted_nodes,
            hypotheses=len(hypothesis_rows) - len(chosen_hypotheses),
            evidence=len(candidates) - len(evidence),
        ),
    )


def render_text(context: GraphContext) -> str:
    """Human-readable rendering that keeps every ID, polarity and uncertainty value."""
    b = context.bounds
    lines = [
        f"graph context for {context.target_concept_id} (learner {context.learner_id})",
        f"selector={context.selector} generated_at={context.generated_at.isoformat()}",
        f"bounds: hops={b.max_hops} nodes={b.max_nodes} hypotheses={b.max_hypotheses} "
        f"evidence={b.max_evidence} max_age_days={b.max_age_days}",
        "curriculum nodes (shared):",
        *(f"  [{n.relation} hops={n.hops}] {n.concept_id}  {n.name}" for n in context.nodes),
        "curriculum prerequisite edges (shared):",
        *(
            f"  {e.edge_id}: {e.prerequisite_id} -> {e.concept_id}"
            for e in context.curriculum_edges
        ),
        "learner hypotheses (inference, tentative):",
        *(
            f"  {h.hypothesis_id} [{h.status}] {h.label} on {h.concept_id} "
            f"confidence={h.confidence:.2f} alternatives={h.alternatives}"
            for h in context.hypotheses
        ),
        "learner evidence (newest first):",
        *(
            f"  {e.polarity.upper()} {e.hypothesis_id} via link {e.link_id} strength="
            f"{e.strength:.2f}: observation {e.observation_id} ({e.source_type} {e.source_id}) "
            f"kind={e.evidence_kind} correct={e.correct} assisted={e.assisted} "
            f"confidence={e.confidence:.2f} observed_at={e.observed_at.isoformat()} "
            f"provenance={e.provenance} - {e.rationale}"
            for e in context.evidence
        ),
        f"omitted by budget: nodes={context.omitted.nodes} "
        f"hypotheses={context.omitted.hypotheses} evidence={context.omitted.evidence}",
        "source ids informing this context:",
        *(f"  {source_id}" for source_id in context.source_ids),
    ]
    return "\n".join(lines)
