"""Curated NetworkX prerequisite DAG, personal evidence links and bounded graph context."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.clock import utc_now
from app.db.database import Database
from app.db.models import (
    ConceptRow,
    EvidenceLinkRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    PrerequisiteEdgeRow,
    SessionRow,
)
from app.db.repositories import NotInScopeError, ScopedRepository
from app.db.seed import DEMO_LEARNER_ADA, DEMO_LEARNER_BEN, seed_uuid
from app.graph.context import build_graph_context, render_text
from app.graph.curriculum import (
    CurriculumGraph,
    CycleError,
    DuplicateEdgeError,
    UnknownConceptError,
    add_prerequisite_edge,
    load_curriculum_graph,
    load_edges,
)
from app.graph.evidence import contradicting_evidence, link_evidence, supporting_evidence
from app.learner.pairing import LearnerScope, issue_pairing_code
from app.schemas import Concept, PrerequisiteEdge
from app.schemas.graph import GraphContextBounds

BACKEND_DIR = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
T0 = datetime(2026, 8, 1, tzinfo=UTC)
LINEAR = "concept.linear_equations"
DISTRIBUTION = "concept.distribution"
ADA_SESSION = seed_uuid("session:ada:1")
ADA_HYPOTHESIS = seed_uuid("hypothesis:ada:1")
SEED_SUPPORT = seed_uuid("evidence-link:ada:1:supports")
SEED_CONTRADICT = seed_uuid("evidence-link:ada:1:contradicts")


def scoped(db: Any, learner_id: str) -> ScopedRepository:
    return ScopedRepository(db, LearnerScope(learner_id=learner_id, credential_id="test"))


def edge_pairs(database: Database) -> set[tuple[str, str]]:
    with database.transaction() as db:
        return {(e.prerequisite_id, e.concept_id) for e in load_edges(db)}


def add_concept(database: Database, concept_id: str) -> None:
    with database.transaction() as db:
        db.add(
            ConceptRow(
                **Concept(
                    id=concept_id, name="Fixture concept", description="Test.", created_at=T0
                ).model_dump()
            )
        )


def add_observation(
    db: Any,
    learner_id: str,
    session_id: str,
    observation_id: str,
    observed_at: datetime,
    concept_id: str = DISTRIBUTION,
    correct: bool | None = True,
) -> None:
    db.add(
        ObservationRow(
            id=observation_id,
            schema_version="observation.v1",
            learner_id=learner_id,
            session_id=session_id,
            source_type="step",
            source_id=f"step-for-{observation_id}",
            evidence_kind="observed_work",
            concept_id=concept_id,
            correct=correct,
            latency_ms=None,
            confidence=0.8,
            assisted=False,
            provenance="submitted",
            observed_at=observed_at,
            recorded_at=observed_at,
        )
    )
    db.flush()


def add_session(db: Any, learner_id: str, session_id: str) -> None:
    db.add(
        SessionRow(
            id=session_id,
            schema_version="session.v1",
            learner_id=learner_id,
            status="active",
            goal=None,
            revision=0,
            provenance="submitted",
            started_at=T0,
            ended_at=None,
        )
    )
    db.flush()


def add_hypothesis(
    db: Any, learner_id: str, hypothesis_id: str, concept_id: str, sources: list[str]
) -> None:
    db.add(
        MisconceptionHypothesisRow(
            id=hypothesis_id,
            schema_version="misconception-hypothesis.v1",
            learner_id=learner_id,
            session_id=None,
            concept_id=concept_id,
            label="Fixture hypothesis",
            description="Test.",
            confidence=0.4,
            alternatives=["Slip"],
            status="tentative",
            evidence_kind="inference",
            source_ids=sources,
            provenance="submitted",
            created_at=T0,
            updated_at=T0,
        )
    )
    db.flush()


# --- Curriculum DAG -------------------------------------------------------------------------


def test_seeded_curriculum_is_a_persisted_networkx_dag(database: Database) -> None:
    with database.transaction() as db:
        graph = load_curriculum_graph(db)
    assert set(graph.graph.nodes) == {
        "concept.multiplication",
        "concept.grouping",
        DISTRIBUTION,
        "concept.equality_operations",
        LINEAR,
    }
    assert graph.graph.number_of_edges() == 4
    order = graph.topological_order()
    assert order.index("concept.multiplication") < order.index(DISTRIBUTION) < order.index(LINEAR)


def test_ancestor_and_one_hop_prerequisite_traversal(database: Database) -> None:
    with database.transaction() as db:
        graph = load_curriculum_graph(db)
    assert set(graph.prerequisites(LINEAR)) == {
        "concept.multiplication",
        "concept.grouping",
        DISTRIBUTION,
        "concept.equality_operations",
    }
    assert graph.prerequisites(LINEAR)["concept.multiplication"] == 3
    assert graph.direct_prerequisites(LINEAR) == [DISTRIBUTION, "concept.equality_operations"]
    assert set(graph.prerequisites(LINEAR, max_hops=1)) == {
        DISTRIBUTION,
        "concept.equality_operations",
    }
    assert graph.prerequisites("concept.multiplication") == {}
    assert graph.dependents("concept.grouping") == {DISTRIBUTION: 1, LINEAR: 2}


def test_bounded_neighborhood(database: Database) -> None:
    with database.transaction() as db:
        graph = load_curriculum_graph(db)
    assert graph.neighborhood(DISTRIBUTION, 0) == {DISTRIBUTION: 0}
    assert graph.neighborhood(DISTRIBUTION, 1) == {
        DISTRIBUTION: 0,
        "concept.grouping": 1,
        LINEAR: 1,
    }
    assert set(graph.neighborhood(DISTRIBUTION, 2)) == {
        DISTRIBUTION,
        "concept.grouping",
        LINEAR,
        "concept.multiplication",
        "concept.equality_operations",
    }


def test_isolated_node_has_no_prerequisites_or_neighbors(database: Database) -> None:
    add_concept(database, "concept.isolated_fixture")
    with database.transaction() as db:
        graph = load_curriculum_graph(db)
    assert graph.isolated() == ["concept.isolated_fixture"]
    assert graph.prerequisites("concept.isolated_fixture") == {}
    assert graph.direct_prerequisites("concept.isolated_fixture") == []
    assert graph.dependents("concept.isolated_fixture") == {}
    assert graph.neighborhood("concept.isolated_fixture", 3) == {"concept.isolated_fixture": 0}


def test_cycle_is_rejected_without_changing_persisted_edges(database: Database) -> None:
    before = edge_pairs(database)
    with pytest.raises(CycleError) as raised, database.transaction() as db:
        add_prerequisite_edge(db, LINEAR, "concept.grouping", NOW)
    assert ("concept.grouping", DISTRIBUTION) in raised.value.cycle
    assert "cycle" in str(raised.value)
    assert edge_pairs(database) == before
    with database.transaction() as db:
        assert len(load_curriculum_graph(db).prerequisites(LINEAR)) == 4


def test_valid_edge_persists_and_duplicates_or_unknowns_are_rejected(database: Database) -> None:
    with database.transaction() as db:
        edge = add_prerequisite_edge(
            db, "concept.multiplication", "concept.equality_operations", NOW
        )
    assert edge.id == "edge.multiplication__equality_operations"
    assert ("concept.multiplication", "concept.equality_operations") in edge_pairs(database)
    with pytest.raises(DuplicateEdgeError), database.transaction() as db:
        add_prerequisite_edge(db, "concept.multiplication", "concept.equality_operations", NOW)
    with pytest.raises(UnknownConceptError), database.transaction() as db:
        add_prerequisite_edge(db, "concept.nope", LINEAR, NOW)


def test_cyclic_rows_written_behind_the_api_fail_to_load(database: Database) -> None:
    with database.transaction() as db:
        db.add(
            PrerequisiteEdgeRow(
                **PrerequisiteEdge(
                    id="edge.bad",
                    prerequisite_id=LINEAR,
                    concept_id="concept.grouping",
                    created_at=NOW,
                ).model_dump()
            )
        )
    with pytest.raises(CycleError), database.transaction() as db:
        load_curriculum_graph(db)


def test_build_rejects_unknown_endpoints() -> None:
    concept = Concept(id="concept.a", name="A", description="A.", created_at=T0)
    edge = PrerequisiteEdge(
        id="e", prerequisite_id="concept.a", concept_id="concept.b", created_at=T0
    )
    with pytest.raises(UnknownConceptError):
        CurriculumGraph.build([concept], [edge])


# --- Personal evidence ----------------------------------------------------------------------


def test_seeded_hypothesis_has_support_and_contradiction(database: Database) -> None:
    with database.transaction() as db:
        repo = scoped(db, DEMO_LEARNER_ADA)
        supports = supporting_evidence(repo, ADA_HYPOTHESIS)
        contradicts = contradicting_evidence(repo, ADA_HYPOTHESIS)
    assert [(link.id, link.observation_id) for link in supports] == [
        (SEED_SUPPORT, seed_uuid("observation:ada:1:0"))
    ]
    assert [(link.id, link.observation_id) for link in contradicts] == [
        (SEED_CONTRADICT, seed_uuid("observation:ada:1:1"))
    ]
    assert contradicts[0].strength < supports[0].strength


def test_personal_evidence_links_never_become_curriculum_edges(database: Database) -> None:
    before = edge_pairs(database)
    with database.transaction() as db:
        repo = scoped(db, DEMO_LEARNER_ADA)
        add_observation(db, DEMO_LEARNER_ADA, ADA_SESSION, "obs-linear", NOW, concept_id=LINEAR)
        link_evidence(
            repo,
            hypothesis_id=ADA_HYPOTHESIS,
            observation_id="obs-linear",
            polarity="contradicts",
            strength=0.5,
            rationale="Solved a linear equation correctly.",
            now=NOW,
        )
    assert edge_pairs(database) == before
    with database.transaction() as db:
        graph = load_curriculum_graph(db)
        assert "obs-linear" not in graph.graph and ADA_HYPOTHESIS not in graph.graph
        assert db.execute(select(EvidenceLinkRow.id)).scalars().all()
    # The link contract has no concept-to-concept fields that could encode a prerequisite.
    assert not {"prerequisite_id", "concept_id"} & set(EvidenceLinkRow.__table__.columns.keys())


def test_evidence_links_reject_other_learners_records(database: Database) -> None:
    with database.transaction() as db:
        add_session(db, DEMO_LEARNER_BEN, "ben-session")
        add_observation(db, DEMO_LEARNER_BEN, "ben-session", "ben-obs", NOW)
    with database.transaction() as db:
        ben = scoped(db, DEMO_LEARNER_BEN)
        with pytest.raises(NotInScopeError):
            link_evidence(
                ben,
                hypothesis_id=ADA_HYPOTHESIS,
                observation_id="ben-obs",
                polarity="supports",
                strength=0.5,
                rationale="x",
                now=NOW,
            )
        with pytest.raises(NotInScopeError):
            supporting_evidence(ben, ADA_HYPOTHESIS)
    # The composite foreign key also rejects a forged cross-learner row.
    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(
            EvidenceLinkRow(
                id="forged",
                schema_version="evidence-link.v1",
                learner_id=DEMO_LEARNER_BEN,
                hypothesis_id=ADA_HYPOTHESIS,
                observation_id="ben-obs",
                polarity="supports",
                strength=0.5,
                rationale="forged",
                provenance="submitted",
                created_at=NOW,
            )
        )


# --- Bounded graph context ------------------------------------------------------------------


def _filtering_fixture(database: Database) -> dict[str, str]:
    """Recent support + recent contradiction, an old support, unrelated and other-learner rows."""
    with database.transaction() as db:
        ada = scoped(db, DEMO_LEARNER_ADA)
        add_session(db, DEMO_LEARNER_ADA, "ada-s2")
        add_observation(
            db, DEMO_LEARNER_ADA, "ada-s2", "ada-old", NOW - timedelta(days=200), correct=False
        )
        add_observation(
            db,
            DEMO_LEARNER_ADA,
            "ada-s2",
            "ada-new-support",
            NOW - timedelta(days=2),
            correct=False,
        )
        add_observation(
            db, DEMO_LEARNER_ADA, "ada-s2", "ada-new-contra", NOW - timedelta(days=1), correct=True
        )
        add_observation(
            db,
            DEMO_LEARNER_ADA,
            "ada-s2",
            "ada-unrelated",
            NOW - timedelta(hours=1),
            concept_id="concept.isolated_fixture",
        )
        add_hypothesis(
            db, DEMO_LEARNER_ADA, "ada-unrelated-hyp", "concept.isolated_fixture", ["ada-unrelated"]
        )
        ids = {}
        for name, obs, hyp, polarity in [
            ("old", "ada-old", ADA_HYPOTHESIS, "supports"),
            ("support", "ada-new-support", ADA_HYPOTHESIS, "supports"),
            ("contra", "ada-new-contra", ADA_HYPOTHESIS, "contradicts"),
            ("unrelated", "ada-unrelated", "ada-unrelated-hyp", "supports"),
        ]:
            ids[name] = link_evidence(
                ada,
                hypothesis_id=hyp,
                observation_id=obs,
                polarity=polarity,  # type: ignore[arg-type]
                strength=0.5,
                rationale=f"fixture {name}",
                now=NOW,
            ).id
        add_session(db, DEMO_LEARNER_BEN, "ben-s1")
        add_observation(db, DEMO_LEARNER_BEN, "ben-s1", "ben-obs", NOW - timedelta(hours=2))
        add_hypothesis(db, DEMO_LEARNER_BEN, "ben-hyp", DISTRIBUTION, ["ben-obs"])
        ids["ben"] = link_evidence(
            scoped(db, DEMO_LEARNER_BEN),
            hypothesis_id="ben-hyp",
            observation_id="ben-obs",
            polarity="supports",
            strength=0.9,
            rationale="ben fixture",
            now=NOW,
        ).id
    return ids


def test_context_keeps_both_polarities_and_filters_old_unrelated_and_foreign(
    database: Database,
) -> None:
    add_concept(database, "concept.isolated_fixture")
    ids = _filtering_fixture(database)
    bounds = GraphContextBounds(max_hops=1, max_nodes=8, max_evidence=2, max_age_days=90)
    with database.transaction() as db:
        context = build_graph_context(scoped(db, DEMO_LEARNER_ADA), DISTRIBUTION, NOW, bounds)

    assert [(e.link_id, e.polarity) for e in context.evidence] == [
        (ids["contra"], "contradicts"),
        (ids["support"], "supports"),
    ]
    selected = set(context.source_ids)
    assert {"ada-new-support", "ada-new-contra", ADA_HYPOTHESIS} <= selected
    assert "step-for-ada-new-contra" in selected
    for excluded in ("ada-old", "ada-unrelated", "ada-unrelated-hyp", "ben-obs", "ben-hyp"):
        assert excluded not in selected
    assert ids["ben"] not in {e.link_id for e in context.evidence}
    assert [h.hypothesis_id for h in context.hypotheses] == [ADA_HYPOTHESIS]
    hypothesis = context.hypotheses[0]
    assert hypothesis.confidence == pytest.approx(0.55)
    assert hypothesis.alternatives and hypothesis.evidence_kind == "inference"
    assert hypothesis.supporting_link_ids == [ids["support"]]
    assert hypothesis.contradicting_link_ids == [ids["contra"]]
    # Seeded links (45 days old) fit the age window but not the 2-item budget.
    assert context.omitted.evidence == 2

    # Curriculum part is the shared DAG only, separate from personal evidence.
    assert {n.concept_id: n.relation for n in context.nodes} == {
        DISTRIBUTION: "target",
        "concept.grouping": "prerequisite",
        LINEAR: "dependent",
    }
    assert {(e.prerequisite_id, e.concept_id) for e in context.curriculum_edges} == {
        ("concept.grouping", DISTRIBUTION),
        (DISTRIBUTION, LINEAR),
    }
    assert {e.edge_id for e in context.curriculum_edges} <= {
        "edge.grouping__distribution",
        "edge.distribution__linear_equations",
    }


def test_context_budget_of_one_and_zero(database: Database) -> None:
    add_concept(database, "concept.isolated_fixture")
    _filtering_fixture(database)
    with database.transaction() as db:
        repo = scoped(db, DEMO_LEARNER_ADA)
        one = build_graph_context(repo, DISTRIBUTION, NOW, GraphContextBounds(max_evidence=1))
        none = build_graph_context(
            repo, DISTRIBUTION, NOW, GraphContextBounds(max_evidence=0, max_nodes=1)
        )
    assert [e.observation_id for e in one.evidence] == ["ada-new-contra"]
    assert none.evidence == [] and [n.concept_id for n in none.nodes] == [DISTRIBUTION]
    assert none.omitted.nodes == 3 and none.curriculum_edges == []


def test_other_learner_context_has_shared_curriculum_but_no_ada_evidence(
    database: Database,
) -> None:
    with database.transaction() as db:
        ada = build_graph_context(scoped(db, DEMO_LEARNER_ADA), LINEAR, NOW)
        ben = build_graph_context(scoped(db, DEMO_LEARNER_BEN), LINEAR, NOW)
    assert ada.nodes == ben.nodes and ada.curriculum_edges == ben.curriculum_edges
    assert {e.link_id for e in ada.evidence} == {SEED_SUPPORT, SEED_CONTRADICT}
    assert ben.evidence == [] and ben.hypotheses == [] and ben.source_ids == []


def test_unknown_concept_is_reported(database: Database) -> None:
    with pytest.raises(UnknownConceptError), database.transaction() as db:
        build_graph_context(scoped(db, DEMO_LEARNER_ADA), "concept.nope", NOW)


def test_text_rendering_keeps_ids_polarity_and_uncertainty(database: Database) -> None:
    with database.transaction() as db:
        text = render_text(build_graph_context(scoped(db, DEMO_LEARNER_ADA), LINEAR, NOW))
    assert "SUPPORTS" in text and "CONTRADICTS" in text
    assert SEED_SUPPORT in text and seed_uuid("step:ada:1:1") in text
    assert "confidence=0.55" in text and "strength=0.30" in text


# --- API and CLI ----------------------------------------------------------------------------


def _pair(database: Database, client: TestClient, learner_id: str) -> dict[str, str]:
    with database.transaction() as db:
        code = issue_pairing_code(db, learner_id, utc_now(), timedelta(minutes=5))
    token = client.post("/pairing/redeem", json={"code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_graph_context_route_is_scoped_by_token(client: TestClient, database: Database) -> None:
    ada = _pair(database, client, DEMO_LEARNER_ADA)
    ben = _pair(database, client, DEMO_LEARNER_BEN)
    params = {"concept_id": DISTRIBUTION, "max_evidence": 2}
    assert client.get("/graph/context", params=params).status_code == 401

    ada_body = client.get("/graph/context", params=params, headers=ada).json()
    assert ada_body["learner_id"] == DEMO_LEARNER_ADA
    assert {e["polarity"] for e in ada_body["evidence"]} == {"supports", "contradicts"}

    ben_response = client.get("/graph/context", params=params, headers=ben)
    assert ben_response.status_code == 200
    ben_body = ben_response.json()
    assert ben_body["learner_id"] == DEMO_LEARNER_BEN
    assert ben_body["evidence"] == [] and ben_body["hypotheses"] == []
    assert ADA_HYPOTHESIS not in ben_response.text and DEMO_LEARNER_ADA not in ben_response.text
    assert ben_body["nodes"] == ada_body["nodes"]

    # Learner IDs cannot be supplied; bounds are enforced.
    assert (
        client.get(
            "/graph/context", params={**params, "max_evidence": 999}, headers=ada
        ).status_code
        == 422
    )
    assert (
        client.get("/graph/context", params={"concept_id": "concept.nope"}, headers=ada).json()[
            "error"
        ]["code"]
        == "unknown_concept"
    )


def _cli(url: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--database-url", url, *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def test_graph_cli_traversal_cycle_rejection_and_context(seeded_db_url: str) -> None:
    validate = json.loads(_cli(seeded_db_url, "graph", "validate").stdout)
    assert validate["is_dag"] is True and validate["prerequisite_edges"] == 4

    prereqs = json.loads(_cli(seeded_db_url, "graph", "prerequisites", "--concept", LINEAR).stdout)
    assert len(prereqs["prerequisites"]) == 4
    assert prereqs["direct_prerequisites"] == [DISTRIBUTION, "concept.equality_operations"]

    rejected = _cli(
        seeded_db_url,
        "graph",
        "add-edge",
        "--prerequisite",
        LINEAR,
        "--concept",
        "concept.grouping",
        check=False,
    )
    assert rejected.returncode != 0 and "cycle" in rejected.stderr
    assert json.loads(_cli(seeded_db_url, "graph", "validate").stdout)["prerequisite_edges"] == 4

    context = json.loads(
        _cli(
            seeded_db_url,
            "graph",
            "context",
            "--learner",
            "ada",
            "--concept",
            LINEAR,
            "--now",
            NOW.isoformat(),
        ).stdout
    )
    assert context["schema_version"] == "graph-context.v1"
    assert {e["link_id"]: e["polarity"] for e in context["evidence"]} == {
        SEED_SUPPORT: "supports",
        SEED_CONTRADICT: "contradicts",
    }
    assert ADA_HYPOTHESIS in context["source_ids"]

    text = _cli(
        seeded_db_url,
        "graph",
        "context",
        "--learner",
        "ben",
        "--concept",
        LINEAR,
        "--format",
        "text",
    ).stdout
    assert "learner evidence" in text and ADA_HYPOTHESIS not in text
    bad = _cli(
        seeded_db_url,
        "graph",
        "context",
        "--learner",
        "ada",
        "--concept",
        LINEAR,
        "--max-evidence",
        "500",
        check=False,
    )
    assert bad.returncode != 0 and "invalid bounds" in bad.stderr
