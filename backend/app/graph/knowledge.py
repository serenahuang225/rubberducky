"""Shared curriculum drawn with one learner's estimates and memories as labels.

The nodes and arrows are the curated prerequisite graph. A learner's work can change the
words on a node. It cannot add an arrow.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import select

from app.db.models import BKTCountedOpportunityRow, ConceptRow, MisconceptionHypothesisRow
from app.db.repositories import ScopedRepository
from app.graph.curriculum import load_curriculum_graph
from app.learner.memory import latest_estimates
from app.schemas.graph import KnowledgeEdge, KnowledgeMap, KnowledgeNode
from app.tracing.contracts import ReadinessBand
from app.tracing.presentation import readiness_band

ReadinessLabel = ReadinessBand | Literal["not_practiced"]

_READINESS_LABEL = {
    "not_practiced": "Not practiced yet",
    "not_enough_evidence": "Not enough independent evidence yet",
    "emerging": "Just starting to show up",
    "developing": "Developing",
    "strong_so_far": "Looking strong so far",
}
_NOTICE = "Shared lesson order. Labels are only this profile's memories and uncalibrated estimates."
_MAX_MEMORIES = 2


def build_knowledge_map(repo: ScopedRepository, now: datetime) -> KnowledgeMap:
    graph = load_curriculum_graph(repo.db)
    names = {
        row.id: row.name
        for row in repo.db.execute(select(ConceptRow.id, ConceptRow.name)).all()
    }
    estimates = {item.concept_id: item for item in latest_estimates(repo)}
    memories: dict[str, list[str]] = {}
    hypotheses = repo.db.execute(
        select(MisconceptionHypothesisRow)
        .where(
            MisconceptionHypothesisRow.learner_id == repo.learner_id,
            MisconceptionHypothesisRow.status != "retracted",
        )
        .order_by(MisconceptionHypothesisRow.updated_at.desc(), MisconceptionHypothesisRow.id)
    ).scalars()
    for hypothesis in hypotheses:
        bucket = memories.setdefault(hypothesis.concept_id, [])
        if len(bucket) < _MAX_MEMORIES:
            bucket.append(hypothesis.label[:200])
    nodes: list[KnowledgeNode] = []
    for concept_id in sorted(graph.graph.nodes, key=lambda cid: names.get(cid, cid)):
        estimate = estimates.get(concept_id)
        readiness: ReadinessLabel
        if estimate is None:
            readiness = "not_practiced"
        else:
            counted = len(
                repo.db.execute(
                    select(BKTCountedOpportunityRow.id).where(
                        BKTCountedOpportunityRow.learner_id == repo.learner_id,
                        BKTCountedOpportunityRow.concept_id == concept_id,
                        BKTCountedOpportunityRow.parameter_version == estimate.parameter_version,
                    )
                ).all()
            )
            readiness = readiness_band(estimate.p_known, counted)
        nodes.append(
            KnowledgeNode(
                concept_id=concept_id,
                name=names.get(concept_id, concept_id),
                readiness=readiness,
                readiness_label=_READINESS_LABEL[readiness],
                memories=memories.get(concept_id, []),
            )
        )
    edges = [
        KnowledgeEdge(prerequisite_id=pre, concept_id=post)
        for pre, post in sorted(graph.graph.edges)
    ]
    return KnowledgeMap(
        learner_id=repo.learner_id,
        generated_at=now,
        notice=_NOTICE,
        nodes=nodes,
        edges=edges,
    )
