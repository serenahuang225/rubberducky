"""Six separately identifiable memory layers, session expiry and restart (VAL-MEM-001)."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.database import Database
from app.db.models import MasteryEstimateRow, MemoryEntryRow, ObservationRow
from app.db.seed import DEMO_LEARNER_ADA, seed_uuid
from app.inference.context import build_tutor_context
from app.learner.memory import memory_layers, set_preference
from app.learner.memory_updates import ProposalScope, apply_memory_updates
from app.schemas import MasteryEstimate
from tests.conftest import bootstrap
from tests.memory_fixtures import DISTRIBUTION, add_observation, scoped
from tests.test_scope_auth import pair_seeded

BACKEND_DIR = Path(__file__).resolve().parents[1]
DAY1 = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
DAY2 = DAY1 + timedelta(days=1)
ADA_OBSERVATION = seed_uuid("observation:ada:1:0")
ADA_HYPOTHESIS = seed_uuid("hypothesis:ada:1")
SEED_NOTE = seed_uuid("memory:ada:1")


def run_cli(url: str, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--database-url", url, *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def first_session_with_tiredness(database: Database) -> dict[str, str]:
    """Day 1: Ada says she is tired; a validated proposal stores it as session context."""
    with database.transaction() as db:
        repo = scoped(db, DEMO_LEARNER_ADA)
        session = repo.start_session("Return visit", DAY1)
        check_in = "checkin-ada-day1"
        add_observation(
            db,
            DEMO_LEARNER_ADA,
            session.id,
            check_in,
            DAY1,
            source_type="check_in",
            source_id=session.id,
            evidence_kind="self_report",
            concept_id=None,
            correct=None,
            confidence=1.0,
        )
        set_preference(repo, "wait_seconds", 30, DAY1)
        estimate = MasteryEstimate(
            id="estimate-ada-distribution",
            learner_id=DEMO_LEARNER_ADA,
            concept_id=DISTRIBUTION,
            algorithm="bkt",
            algorithm_version="bkt-numpy.v1",
            parameter_version="bkt-handset.v1",
            p_known=0.31,
            source_observation_ids=[ADA_OBSERVATION],
            provenance="submitted",
            computed_at=DAY1,
        )
        db.add(MasteryEstimateRow(**estimate.model_dump()))
        result = apply_memory_updates(
            repo,
            [
                {
                    "operation": "create_session_context",
                    "learner_id": DEMO_LEARNER_ADA,
                    "session_id": session.id,
                    "content": "Said they are tired today; offered a slower start.",
                    "evidence_kind": "self_report",
                    "confidence": 0.9,
                    "source_ids": [check_in],
                    "expires_at": (DAY1 + timedelta(hours=3)).isoformat(),
                },
                {
                    "operation": "create_episodic_note",
                    "learner_id": DEMO_LEARNER_ADA,
                    "session_id": session.id,
                    "content": "Distributing to both terms may still need a visual grouping cue.",
                    "evidence_kind": "inference",
                    "confidence": 0.5,
                    "source_ids": [ADA_OBSERVATION, ADA_HYPOTHESIS],
                    "review_at": (DAY1 + timedelta(days=7)).isoformat(),
                },
            ],
            ProposalScope(session_id=session.id, turn_id="turn-day1-1"),
            DAY1,
        )
        assert result.status == "applied", result
        context_id, note_id = result.applied_ids
    return {"session": session.id, "context": context_id, "note": note_id, "check_in": check_in}


def correctness_observations(database: Database) -> int:
    with database.transaction() as db:
        return int(
            db.execute(
                select(func.count()).where(
                    ObservationRow.learner_id == DEMO_LEARNER_ADA,
                    ObservationRow.correct.is_not(None),
                )
            ).scalar_one()
        )


def test_six_layers_and_metadata_survive_a_process_restart(
    seeded_db_url: str, database: Database
) -> None:
    ids = first_session_with_tiredness(database)
    database.dispose()

    layers = run_cli(
        seeded_db_url,
        "memory", "layers", "--learner", "ada", "--session", ids["session"],
        "--now", (DAY1 + timedelta(hours=1)).isoformat(),
    )  # fmt: skip
    assert layers["schema_version"] == "memory-layers.v1"
    # 1. Raw evidence: the check-in is a self-report without correctness.
    check_in = next(o for o in layers["raw_evidence"] if o["id"] == ids["check_in"])
    assert check_in["evidence_kind"] == "self_report" and check_in["correct"] is None
    # 2. Derived beliefs keep sources and algorithm/parameter versions.
    hypothesis = next(h for h in layers["derived_hypotheses"] if h["id"] == ADA_HYPOTHESIS)
    assert hypothesis["evidence_kind"] == "inference" and hypothesis["source_ids"]
    estimate = layers["derived_estimates"][0]
    assert estimate["parameter_version"] == "bkt-handset.v1"
    assert estimate["algorithm_version"] == "bkt-numpy.v1"
    assert estimate["source_observation_ids"] == [ADA_OBSERVATION]
    assert estimate["calibrated"] is False
    # 3. Editable preferences: the learner's edit, with update metadata.
    [preference] = layers["preferences"]
    assert preference["key"] == "wait_seconds" and preference["value"] == 30
    assert preference["updated_by"] == "learner" and preference["provenance"] == "submitted"
    assert preference["updated_at"] == DAY1.isoformat().replace("+00:00", "Z")
    # 4. Session context: this session only, with origin, turn and expiry.
    session_context = layers["session_context"]
    assert session_context["current_session_id"] == ids["session"]
    [tired] = session_context["active"]
    assert tired["id"] == ids["context"] and tired["layer"] == "session_context"
    assert tired["origin"] == "tutor_proposal" and tired["turn_id"] == "turn-day1-1"
    assert tired["source_ids"] == [ids["check_in"]] and tired["expires_at"]
    # 5. Episodic notes carry sources and review state.
    notes = {n["entry"]["id"]: n for n in layers["episodic_notes"]}
    new_note = notes[ids["note"]]
    assert new_note["entry"]["source_ids"] == [ADA_OBSERVATION, ADA_HYPOTHESIS]
    assert new_note["entry"]["evidence_kind"] == "inference"
    assert new_note["entry"]["status"] == "active" and new_note["review_due"] is False
    assert notes[SEED_NOTE]["review_due"] is True  # seed note's review date has passed
    # 6. Persona configuration with its selection timestamps.
    persona = layers["persona"]
    assert persona["personality"] == "gentle" and persona["chosen_at"]


def test_new_session_does_not_turn_yesterdays_tiredness_into_todays_fact(
    seeded_db_url: str, database: Database
) -> None:
    ids = first_session_with_tiredness(database)
    before_correctness = correctness_observations(database)
    with database.transaction() as db:
        today = scoped(db, DEMO_LEARNER_ADA).start_session("Next day", DAY2)
        today_id = today.id
    database.dispose()

    # Restart, then read the new session from a fresh process.
    layers = run_cli(
        seeded_db_url,
        "memory", "layers", "--learner", "ada", "--session", today_id,
        "--now", DAY2.isoformat(),
    )  # fmt: skip
    assert layers["session_context"]["active"] == []
    assert layers["session_context"]["recheck_needed"] is True
    assert layers["session_context"]["expired_count"] >= 1

    with database.transaction() as db:
        row = db.get(MemoryEntryRow, ids["context"])
        assert row is not None and row.status == "expired"
        context = build_tutor_context(
            scoped(db, DEMO_LEARNER_ADA), DISTRIBUTION, DAY2, session_id=today_id
        )
    assert "tired" not in context.serialized
    assert ids["context"] not in context.citable_ids
    assert context.payload.session_context_recheck is True
    assert "session_context_needs_recheck" in context.payload.gaps
    # Tiredness never became a correctness observation or a mastery change.
    assert correctness_observations(database) == before_correctness
    with database.transaction() as db:
        estimate = db.get(MasteryEstimateRow, "estimate-ada-distribution")
        assert estimate is not None and estimate.p_known == 0.31


def test_session_context_expires_at_its_time_even_within_the_session(
    database: Database,
) -> None:
    ids = first_session_with_tiredness(database)
    with database.transaction() as db:
        repo = scoped(db, DEMO_LEARNER_ADA)
        during = memory_layers(repo, DAY1 + timedelta(hours=2), ids["session"])
        after = memory_layers(repo, DAY1 + timedelta(hours=3), ids["session"])
        context = build_tutor_context(
            repo, DISTRIBUTION, DAY1 + timedelta(hours=3), session_id=ids["session"]
        )
    assert [e.id for e in during.session_context.active] == [ids["context"]]
    assert after.session_context.active == []
    assert "tired" not in context.serialized


def test_ending_a_session_expires_its_context(database: Database) -> None:
    ids = first_session_with_tiredness(database)
    with database.transaction() as db:
        scoped(db, DEMO_LEARNER_ADA).end_session(ids["session"], DAY1 + timedelta(hours=1))
    with database.transaction() as db:
        row = db.get(MemoryEntryRow, ids["context"])
        assert row is not None and row.status == "expired"
        note = db.get(MemoryEntryRow, ids["note"])
        assert note is not None and note.status == "active"


def test_memory_routes_are_scoped_to_the_paired_learner(
    client: TestClient, database: Database
) -> None:
    ada = pair_seeded(database, client, DEMO_LEARNER_ADA)
    other_id, other = bootstrap(client, "Other learner")
    ada_session = client.post("/sessions", json={"goal": "Practice"}, headers=ada).json()

    own = client.get("/memory/layers", params={"session_id": ada_session["id"]}, headers=ada)
    assert own.status_code == 200
    body = own.json()
    assert body["learner_id"] == DEMO_LEARNER_ADA
    assert body["session_context"]["current_session_id"] == ada_session["id"]
    assert any(n["entry"]["id"] == SEED_NOTE for n in body["episodic_notes"])

    foreign = client.get(
        "/memory/layers", params={"session_id": ada_session["id"]}, headers=other
    )
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "not_found"
    theirs = client.get("/memory/layers", headers=other).json()
    assert theirs["learner_id"] == other_id
    assert theirs["raw_evidence"] == [] and theirs["episodic_notes"] == []
    assert theirs["persona"] is None

    context = client.get(
        "/memory/context", params={"concept_id": DISTRIBUTION}, headers=ada
    ).json()
    assert ADA_HYPOTHESIS in context["citable_ids"]
    other_context = client.get(
        "/memory/context", params={"concept_id": DISTRIBUTION}, headers=other
    )
    assert other_context.status_code == 200
    assert ADA_HYPOTHESIS not in other_context.text
    assert other_context.json()["payload"]["sufficiency"] == "limited"
    cross = client.get(
        "/memory/context",
        params={"concept_id": DISTRIBUTION, "session_id": ada_session["id"]},
        headers=other,
    )
    assert cross.status_code == 404
    unknown = client.get("/memory/context", params={"concept_id": "concept.nope"}, headers=ada)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "unknown_concept"
    assert client.get("/memory/layers").status_code == 401
