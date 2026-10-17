"""Curated prerequisite DAG backed by persisted ``concepts`` and ``prerequisite_edges``.

The graph is rebuilt from the database for each use and only ever reads curriculum tables,
so learner-specific evidence cannot add, remove or reorder prerequisites. An edge
``prerequisite -> concept`` means the prerequisite should be learned first.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import ConceptRow, PrerequisiteEdgeRow
from app.schemas import Concept, PrerequisiteEdge


class CurriculumGraphError(ValueError):
    """Base class for rejected curriculum graph operations."""


class UnknownConceptError(CurriculumGraphError):
    def __init__(self, concept_id: str) -> None:
        super().__init__(f"unknown concept: {concept_id}")
        self.concept_id = concept_id


class CycleError(CurriculumGraphError):
    def __init__(self, cycle: list[tuple[str, str]]) -> None:
        path = " -> ".join([cycle[0][0], *(target for _, target in cycle)])
        super().__init__(f"prerequisite cycle rejected: {path}")
        self.cycle = cycle


class DuplicateEdgeError(CurriculumGraphError):
    pass


@dataclass(frozen=True)
class CurriculumGraph:
    """An immutable view over a validated prerequisite DAG."""

    graph: nx.DiGraph

    @classmethod
    def build(
        cls, concepts: Iterable[Concept], edges: Iterable[PrerequisiteEdge]
    ) -> "CurriculumGraph":
        graph: nx.DiGraph = nx.DiGraph()
        for concept in concepts:
            graph.add_node(concept.id, name=concept.name)
        for edge in edges:
            for endpoint in (edge.prerequisite_id, edge.concept_id):
                if endpoint not in graph:
                    raise UnknownConceptError(endpoint)
            graph.add_edge(edge.prerequisite_id, edge.concept_id, edge_id=edge.id)
        _require_acyclic(graph)
        return cls(nx.freeze(graph))

    def require(self, concept_id: str) -> None:
        if concept_id not in self.graph:
            raise UnknownConceptError(concept_id)

    def name(self, concept_id: str) -> str:
        self.require(concept_id)
        return str(self.graph.nodes[concept_id]["name"])

    def edge_id(self, prerequisite_id: str, concept_id: str) -> str:
        return str(self.graph.edges[prerequisite_id, concept_id]["edge_id"])

    def prerequisites(self, concept_id: str, max_hops: int | None = None) -> dict[str, int]:
        """Prerequisites of ``concept_id`` mapped to their hop distance (1 = direct)."""
        self.require(concept_id)
        return self._within(self.graph.reverse(copy=False), concept_id, max_hops)

    def direct_prerequisites(self, concept_id: str) -> list[str]:
        self.require(concept_id)
        return sorted(self.graph.predecessors(concept_id))

    def dependents(self, concept_id: str, max_hops: int | None = None) -> dict[str, int]:
        """Concepts that build on ``concept_id``, mapped to their hop distance."""
        self.require(concept_id)
        return self._within(self.graph, concept_id, max_hops)

    def neighborhood(self, concept_id: str, max_hops: int) -> dict[str, int]:
        """All concepts within ``max_hops`` edges in either direction, including the target."""
        self.require(concept_id)
        lengths = nx.single_source_shortest_path_length(
            self.graph.to_undirected(as_view=True), concept_id, cutoff=max_hops
        )
        return dict(sorted(lengths.items(), key=lambda item: (item[1], item[0])))

    def isolated(self) -> list[str]:
        return sorted(nx.isolates(self.graph))

    def topological_order(self) -> list[str]:
        # Lexicographic tie-breaking keeps output stable across runs.
        return list(nx.lexicographical_topological_sort(self.graph))

    @staticmethod
    def _within(graph: nx.DiGraph, source: str, max_hops: int | None) -> dict[str, int]:
        lengths = nx.single_source_shortest_path_length(graph, source, cutoff=max_hops)
        lengths.pop(source, None)
        return dict(sorted(lengths.items(), key=lambda item: (item[1], item[0])))


def _require_acyclic(graph: nx.DiGraph) -> None:
    if not nx.is_directed_acyclic_graph(graph):
        raise CycleError([(str(u), str(v)) for u, v in nx.find_cycle(graph)])


def default_edge_id(prerequisite_id: str, concept_id: str) -> str:
    return f"edge.{prerequisite_id.removeprefix('concept.')}__{concept_id.removeprefix('concept.')}"


def load_concepts(db: DbSession) -> list[Concept]:
    rows = db.execute(select(ConceptRow).order_by(ConceptRow.id)).scalars()
    return [Concept.model_validate(row) for row in rows]


def load_edges(db: DbSession) -> list[PrerequisiteEdge]:
    rows = db.execute(select(PrerequisiteEdgeRow).order_by(PrerequisiteEdgeRow.id)).scalars()
    return [PrerequisiteEdge.model_validate(row) for row in rows]


def load_curriculum_graph(db: DbSession) -> CurriculumGraph:
    return CurriculumGraph.build(load_concepts(db), load_edges(db))


def add_prerequisite_edge(
    db: DbSession,
    prerequisite_id: str,
    concept_id: str,
    now: datetime,
    edge_id: str | None = None,
) -> PrerequisiteEdge:
    """Persist a curated edge only if the resulting graph is still a DAG.

    Validation runs on a copy before anything is written, so a rejected edge leaves the
    stored curriculum exactly as it was.
    """
    current = load_curriculum_graph(db)
    current.require(prerequisite_id)
    current.require(concept_id)
    if current.graph.has_edge(prerequisite_id, concept_id):
        raise DuplicateEdgeError(f"edge already exists: {prerequisite_id} -> {concept_id}")
    edge = PrerequisiteEdge(
        id=edge_id or default_edge_id(prerequisite_id, concept_id),
        prerequisite_id=prerequisite_id,
        concept_id=concept_id,
        created_at=now,
    )
    candidate = nx.DiGraph(current.graph)
    candidate.add_edge(prerequisite_id, concept_id, edge_id=edge.id)
    _require_acyclic(candidate)
    db.add(PrerequisiteEdgeRow(**edge.model_dump()))
    db.flush()
    return edge


def validation_report(graph: CurriculumGraph) -> dict[str, object]:
    return {
        "is_dag": True,
        "concepts": graph.graph.number_of_nodes(),
        "prerequisite_edges": graph.graph.number_of_edges(),
        "isolated_concepts": graph.isolated(),
        "topological_order": graph.topological_order(),
    }
