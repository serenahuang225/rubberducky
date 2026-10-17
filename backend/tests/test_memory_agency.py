"""Memory inspection, correction, deletion and removal with derived-state replay (VAL-MEM-004..006).

Everything runs over the real API against a migrated, file-backed SQLite database. BKT numbers
come from the labeled replay fixture (10/19 after one counted opportunity; 67/310 once the
second is corrected to wrong), and restart is proved in a fresh interpreter.
"""

import json
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.clock import utc_now
from app.db.database import Database
from app.db.models import (
    AssessmentRow,
    Base,
    BKTCountedOpportunityRow,
    DeletionTombstoneRow,
    EvidenceCorrectionRow,
    HintRow,
    LearnerRow,
    MasteryEstimateRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SceneObjectRow,
    StepRow,
    TutorTurnRow,
)
from app.db.seed import (
    DEMO_LEARNER_ADA,
    DEMO_LEARNER_BEN,
    insert_missing,
    seed_database,
    seed_uuid,
)
from app.inference.context import build_tutor_context
from app.inference.providers import MockTutorProvider, ProviderLabel
from app.learner.memory import memory_layers
from app.learner.removal import learner_inventory
from app.tracing.contracts import DEFAULT_PARAMETERS
from app.tracing.fixtures import FIXTURE_LEARNER_ID, bkt_fixture_records
from tests.conftest import bootstrap
from tests.memory_fixtures import scoped
from tests.test_scope_auth import pair_seeded
from tests.test_tutor_turns import check_in, key, post_turn, start_session

BACKEND_DIR = Path(__file__).resolve().parents[1]
DISTRIBUTION = "concept.distribution"
LINEAR = "concept.linear_equations"
VERSION = DEFAULT_PARAMETERS.parameter_version

ADA_SESSION = seed_uuid("session:ada:1")
ADA_STEP = seed_uuid("step:ada:1:0")
ADA_OBSERVATION = seed_uuid("observation:ada:1:0")
ADA_HYPOTHESIS = seed_uuid("hypothesis:ada:1")
ADA_NOTE = seed_uuid("memory:ada:1")
ADA_ATTEMPT = seed_uuid("attempt:ada:1")


def fixture_observation(name: str) -> str:
    return seed_uuid(f"observation:bkt-fixture:{name}")


@pytest.fixture
def ada(client: TestClient, database: Database) -> dict[str, str]:
    # The seeded note's review date is fictional and long past; move it forward so these
    # tests exercise correction rather than review expiry.
    with database.transaction() as db:
        note = db.get(MemoryEntryRow, ADA_NOTE)
        assert note is not None
        note.review_at = utc_now() + timedelta(days=30)
    return pair_seeded(database, client, DEMO_LEARNER_ADA)


@pytest.fixture
def ben(client: TestClient, database: Database) -> dict[str, str]:
    return pair_seeded(database, client, DEMO_LEARNER_BEN)


@pytest.fixture
def bkt_learner(client: TestClient, database: Database) -> dict[str, str]:
    with database.transaction() as db:
        insert_missing(db, bkt_fixture_records())
    return pair_seeded(database, client, FIXTURE_LEARNER_ID)


def estimate(database: Database, learner_id: str, concept_id: str = LINEAR) -> float | None:
    with database.transaction() as db:
        row = db.execute(
            select(MasteryEstimateRow).where(
                MasteryEstimateRow.learner_id == learner_id,
                MasteryEstimateRow.concept_id == concept_id,
                MasteryEstimateRow.parameter_version == VERSION,
            )
        ).scalar_one_or_none()
    return None if row is None else row.p_known


def probe_restart(url: str, learner_id: str, *statements: str) -> dict[str, Any]:
    """Read persisted state in a fresh interpreter; each statement is an expression."""
    script = (
        "import json, sys\n"
        "from sqlalchemy import select\n"
        "from app.db.database import Database\n"
        "from app.db.models import MasteryEstimateRow, ObservationRow, "
        "MemoryEntryRow, MisconceptionHypothesisRow, DeletionTombstoneRow\n"
        "database = Database(sys.argv[1])\n"
        "out = {}\n"
        "with database.transaction() as db:\n"
        "    rows = db.execute(select(MasteryEstimateRow.concept_id, MasteryEstimateRow.p_known,"
        " MasteryEstimateRow.parameter_version).where(MasteryEstimateRow.learner_id == sys.argv[2])"
        ").all()\n"
        "    out['estimates'] = {f'{r[0]}|{r[2]}': r[1] for r in rows}\n"
        "    out['observations'] = sorted(db.execute(select(ObservationRow.id).where("
        "ObservationRow.learner_id == sys.argv[2])).scalars())\n"
        "    out['notes'] = sorted(db.execute(select(MemoryEntryRow.id)).scalars())\n"
        "    out['hypotheses'] = sorted(\n"
        "        db.execute(select(MisconceptionHypothesisRow.id)).scalars())\n"
        "    out['tombstones'] = list(\n"
        "        db.execute(select(DeletionTombstoneRow.record_id)).scalars())\n"
        "database.dispose()\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, url, learner_id],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def run_cli(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", "--database-url", url, *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )


class TestBktCorrectionAndDeletion:
    def test_correcting_the_second_counted_opportunity_recomputes_from_raw_history(
        self,
        client: TestClient,
        database: Database,
        bkt_learner: dict[str, str],
        seeded_db_url: str,
    ) -> None:
        response = client.post(
            f"/memory/evidence/{fixture_observation('transfer')}/correction",
            json={"correct": False},
            headers=bkt_learner,
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["changed"] is True
        assert receipt["original"] == "correct" and receipt["current"] == "not correct"
        assert VERSION in receipt["effects"]["recomputed_parameter_versions"]
        assert estimate(database, FIXTURE_LEARNER_ID) == pytest.approx(67 / 310)
        shown = {e["concept_id"]: e["p_known"] for e in receipt["effects"]["mastery_estimates"]}
        assert shown[LINEAR] == pytest.approx(67 / 310)
        # The original judgement is preserved for audit, never presented as measured.
        with database.transaction() as db:
            correction = db.execute(select(EvidenceCorrectionRow)).scalar_one()
            assert correction.original_correct is True and correction.corrected_correct is False

        probe = probe_restart(seeded_db_url, FIXTURE_LEARNER_ID)
        assert probe["estimates"][f"{LINEAR}|{VERSION}"] == pytest.approx(67 / 310)

    def test_correction_is_idempotent_and_reversible_to_the_raw_numbers(
        self, client: TestClient, database: Database, bkt_learner: dict[str, str]
    ) -> None:
        path = f"/memory/evidence/{fixture_observation('transfer')}/correction"
        client.post(path, json={"correct": False}, headers=bkt_learner)
        again = client.post(path, json={"correct": False}, headers=bkt_learner)
        assert again.status_code == 200 and again.json()["changed"] is False
        back = client.post(path, json={"correct": True}, headers=bkt_learner)
        assert back.json()["original"] == "correct"
        assert estimate(database, FIXTURE_LEARNER_ID) == pytest.approx(0.82, abs=0.005)

    def test_deleting_the_second_counted_opportunity_leaves_first_only_numbers(
        self,
        client: TestClient,
        database: Database,
        bkt_learner: dict[str, str],
        seeded_db_url: str,
    ) -> None:
        response = client.delete(
            f"/memory/evidence/{fixture_observation('transfer')}", headers=bkt_learner
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert fixture_observation("transfer") in receipt["deleted_ids"]
        assert receipt["tombstones_written"] == 2  # observation and its assessment
        assert estimate(database, FIXTURE_LEARNER_ID) == pytest.approx(10 / 19)
        with database.transaction() as db:
            ledger = db.execute(
                select(func.count())
                .select_from(BKTCountedOpportunityRow)
                .where(BKTCountedOpportunityRow.learner_id == FIXTURE_LEARNER_ID)
            ).scalar_one()
            assert ledger == 1
            assert db.get(ObservationRow, fixture_observation("transfer")) is None

        probe = probe_restart(seeded_db_url, FIXTURE_LEARNER_ID)
        assert probe["estimates"][f"{LINEAR}|{VERSION}"] == pytest.approx(10 / 19)
        assert fixture_observation("transfer") not in probe["observations"]
        assert fixture_observation("transfer") in probe["tombstones"]

    def test_deleted_evidence_is_not_resurrected_by_reseeding_after_restart(
        self,
        client: TestClient,
        database: Database,
        bkt_learner: dict[str, str],
        seeded_db_url: str,
    ) -> None:
        client.delete(f"/memory/evidence/{fixture_observation('transfer')}", headers=bkt_learner)
        run_cli(seeded_db_url, "seed")
        run_cli(seeded_db_url, "tracing", "fixture")
        state = json.loads(
            run_cli(seeded_db_url, "tracing", "state", "--learner", "bkt-fixture").stdout
        )
        assert state["estimates"][0]["p_known"] == pytest.approx(10 / 19)
        probe = probe_restart(seeded_db_url, FIXTURE_LEARNER_ID)
        assert fixture_observation("transfer") not in probe["observations"]
        assert fixture_observation("first") in probe["observations"]

    def test_unjudged_evidence_cannot_be_corrected(
        self, client: TestClient, bkt_learner: dict[str, str]
    ) -> None:
        response = client.post(
            f"/memory/evidence/{fixture_observation('tired')}/correction",
            json={"correct": True},
            headers=bkt_learner,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "not_correctable"


class TestHypothesesAndNotes:
    def test_correcting_the_cited_evidence_retracts_dependents_and_removes_them_from_context(
        self, client: TestClient, database: Database, ada: dict[str, str]
    ) -> None:
        with database.transaction() as db:
            repo = scoped(db, DEMO_LEARNER_ADA)
            before = build_tutor_context(repo, DISTRIBUTION, utc_now())
        assert ADA_HYPOTHESIS in before.citable_ids and ADA_NOTE in before.citable_ids

        response = client.post(
            f"/memory/evidence/{ADA_OBSERVATION}/correction",
            json={"correct": True},
            headers=ada,
        )
        assert response.status_code == 200, response.text
        effects = response.json()["effects"]
        assert ADA_HYPOTHESIS in effects["hypotheses_retracted"]
        assert ADA_NOTE in effects["notes_flagged_for_review"]
        with database.transaction() as db:
            repo = scoped(db, DEMO_LEARNER_ADA)
            hypothesis = db.get(MisconceptionHypothesisRow, ADA_HYPOTHESIS)
            assert hypothesis is not None and hypothesis.status == "retracted"
            context = build_tutor_context(repo, DISTRIBUTION, utc_now())
        assert ADA_HYPOTHESIS not in context.citable_ids
        assert ADA_NOTE not in context.citable_ids

    def test_deleting_evidence_removes_dependent_beliefs_and_notes_with_tombstones_only(
        self, client: TestClient, database: Database, ada: dict[str, str], seeded_db_url: str
    ) -> None:
        response = client.delete(f"/memory/evidence/{ADA_OBSERVATION}", headers=ada)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert ADA_HYPOTHESIS in receipt["effects"]["hypotheses_deleted"]
        assert ADA_NOTE in receipt["effects"]["notes_deleted"]
        assert {ADA_OBSERVATION, ADA_STEP, ADA_HYPOTHESIS, ADA_NOTE} <= set(receipt["deleted_ids"])

        with database.transaction() as db:
            assert db.get(ObservationRow, ADA_OBSERVATION) is None
            assert db.get(StepRow, ADA_STEP) is None
            assert db.get(MisconceptionHypothesisRow, ADA_HYPOTHESIS) is None
            assert db.get(MemoryEntryRow, ADA_NOTE) is None
            repo = scoped(db, DEMO_LEARNER_ADA)
            context = build_tutor_context(repo, DISTRIBUTION, utc_now())
            layers = memory_layers(repo, utc_now(), None)
            tombstones = list(db.execute(select(DeletionTombstoneRow)).scalars())
        assert {ADA_OBSERVATION, ADA_HYPOTHESIS, ADA_NOTE}.isdisjoint(context.citable_ids)
        assert ADA_NOTE not in layers.model_dump_json()
        assert "Grouping both terms helped" not in context.serialized
        assert "Partial distribution" not in context.serialized
        # Tombstones hold identifiers and reasons, never deleted text.
        assert {t.record_id for t in tombstones} >= {ADA_OBSERVATION, ADA_HYPOTHESIS, ADA_NOTE}
        dumped = json.dumps([[t.record_kind, t.record_id, t.reason] for t in tombstones])
        assert "Grouping both" not in dumped and "2x + 3 = 14" not in dumped

        inspection = client.get("/memory/inspect", headers=ada).json()
        assert {ADA_OBSERVATION, ADA_HYPOTHESIS, ADA_NOTE}.isdisjoint(
            {item["id"] for item in inspection["items"]}
        )
        assert ADA_OBSERVATION not in json.dumps(inspection)
        assert client.get(f"/memory/sources/{ADA_STEP}", headers=ada).status_code == 404

        run_cli(seeded_db_url, "seed")
        probe = probe_restart(seeded_db_url, DEMO_LEARNER_ADA)
        assert ADA_OBSERVATION not in probe["observations"]
        assert ADA_HYPOTHESIS not in probe["hypotheses"] and ADA_NOTE not in probe["notes"]

    def test_corrected_note_is_provenance_distinct_and_the_old_wording_is_not_current(
        self, client: TestClient, database: Database, ada: dict[str, str]
    ) -> None:
        response = client.post(
            f"/memory/notes/{ADA_NOTE}/correction",
            json={"content": "I can group both terms on my own now."},
            headers=ada,
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        replacement_id = receipt["replacement_id"]
        assert replacement_id and replacement_id != ADA_NOTE
        assert receipt["current"] == "I can group both terms on my own now."
        with database.transaction() as db:
            old = db.get(MemoryEntryRow, ADA_NOTE)
            new = db.get(MemoryEntryRow, replacement_id)
            assert old is not None and new is not None
            assert old.status == "corrected" and new.status == "active"
            assert new.origin == "learner" and new.supersedes_id == ADA_NOTE
            assert new.provenance == "submitted" and new.evidence_kind == "self_report"
            repo = scoped(db, DEMO_LEARNER_ADA)
            context = build_tutor_context(repo, DISTRIBUTION, utc_now())
            layers = memory_layers(repo, utc_now(), None)
        assert "Grouping both terms helped" not in context.serialized
        assert "I can group both terms" in context.serialized
        active = [n.entry.id for n in layers.episodic_notes if n.entry.status == "active"]
        assert replacement_id in active and ADA_NOTE not in active

        items = client.get("/memory/inspect", headers=ada).json()["items"]
        by_id = {item["id"]: item for item in items}
        shown = by_id[replacement_id]
        assert shown["origin"] == "learner" and shown["state"] == "current"
        assert shown["supersedes_id"] == ADA_NOTE
        assert shown["correction"]["original"].startswith("Grouping both terms")
        assert by_id.get(ADA_NOTE, {}).get("state", "corrected") != "current"

    def test_deleting_a_note_removes_every_version(
        self, client: TestClient, database: Database, ada: dict[str, str]
    ) -> None:
        replacement = client.post(
            f"/memory/notes/{ADA_NOTE}/correction",
            json={"content": "Replacement wording."},
            headers=ada,
        ).json()["replacement_id"]
        response = client.delete(f"/memory/notes/{replacement}", headers=ada)
        assert response.status_code == 200, response.text
        assert {ADA_NOTE, replacement} <= set(response.json()["deleted_ids"])
        with database.transaction() as db:
            assert db.get(MemoryEntryRow, ADA_NOTE) is None
            assert db.get(MemoryEntryRow, replacement) is None
            assert db.get(ObservationRow, ADA_OBSERVATION) is not None

    def test_deleting_a_hypothesis_leaves_the_raw_evidence(
        self, client: TestClient, database: Database, ada: dict[str, str]
    ) -> None:
        response = client.delete(f"/memory/hypotheses/{ADA_HYPOTHESIS}", headers=ada)
        assert response.status_code == 200, response.text
        with database.transaction() as db:
            assert db.get(MisconceptionHypothesisRow, ADA_HYPOTHESIS) is None
            assert db.get(ObservationRow, ADA_OBSERVATION) is not None
        second = client.delete(f"/memory/hypotheses/{ADA_HYPOTHESIS}", headers=ada)
        assert second.status_code == 404

    def test_empty_or_oversized_note_correction_is_rejected(
        self, client: TestClient, ada: dict[str, str]
    ) -> None:
        for content in ("", "x" * 301):
            response = client.post(
                f"/memory/notes/{ADA_NOTE}/correction", json={"content": content}, headers=ada
            )
            assert response.status_code == 422


class TestInspectionAndSources:
    def test_inspection_explains_sources_uncertainty_and_actions(
        self, client: TestClient, ada: dict[str, str]
    ) -> None:
        response = client.get("/memory/inspect", headers=ada)
        assert response.status_code == 200
        body = response.json()
        items = {item["id"]: item for item in body["items"]}
        hypothesis = items[ADA_HYPOTHESIS]
        assert hypothesis["kind"] == "hypothesis"
        assert hypothesis["uncertainty"]["explanation"]
        assert hypothesis["why_it_matters"]
        source_ids = {s["id"] for s in hypothesis["sources"]}
        assert {ADA_STEP, ADA_OBSERVATION} == source_ids
        step = next(s for s in hypothesis["sources"] if s["id"] == ADA_STEP)
        assert step["available"] is True and "2x + 3 = 14" in step["excerpt"]
        assert any(a["action"] == "delete" for a in hypothesis["actions"])
        assert "uncalibrated" in body["notice"]
        assert all(i["kind"] != "estimate" or i["state"] == "uncalibrated" for i in body["items"])

    def test_source_endpoint_returns_a_plain_language_explanation(
        self, client: TestClient, ada: dict[str, str]
    ) -> None:
        response = client.get(f"/memory/sources/{ADA_STEP}", headers=ada)
        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "step" and body["available"] is True
        assert body["label"] and "2x + 3 = 14" in body["excerpt"]

    def test_inspection_limit_is_bounded(self, client: TestClient, ada: dict[str, str]) -> None:
        assert client.get("/memory/inspect?limit=0", headers=ada).status_code == 422
        assert client.get("/memory/inspect?limit=51", headers=ada).status_code == 422
        items = client.get("/memory/inspect?limit=1", headers=ada).json()["items"]
        # The limit applies to each layer, so no layer repeats more than once.
        layers = [item["layer"] for item in items]
        assert len(layers) == len(set(layers))


class TestPendingTurns:
    def _blocked_work_turn(
        self, client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ):
        entered = threading.Event()
        release = threading.Event()
        mock = MockTutorProvider()

        class Blocking:
            def label(self) -> ProviderLabel:
                return mock.label()

            def draft(self, inputs):
                entered.set()
                assert release.wait(timeout=20)
                return mock.draft(inputs)

        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        monkeypatch.setattr("app.tutor.coordinator.get_provider", lambda settings: Blocking())
        outcome: dict[str, Any] = {}

        def run() -> None:
            outcome["response"] = post_turn(
                client,
                headers,
                session_id,
                "work",
                {"expected_revision": 1, "text": "2x + 3 = 14"},
                key("pending"),
            )

        thread = threading.Thread(target=run)
        thread.start()
        assert entered.wait(timeout=20)
        return session_id, outcome, release, thread

    def _work_observation(self, database: Database, learner_id: str, session_id: str) -> str:
        with database.transaction() as db:
            rows = list(
                db.execute(
                    select(ObservationRow.id).where(
                        ObservationRow.learner_id == learner_id,
                        ObservationRow.session_id == session_id,
                        ObservationRow.correct.is_not(None),
                    )
                ).scalars()
            )
        assert len(rows) == 1
        return rows[0]

    @pytest.mark.parametrize("operation", ["correct", "delete"])
    def test_pending_turn_built_on_changed_evidence_is_invalidated_and_cannot_commit(
        self,
        client: TestClient,
        database: Database,
        monkeypatch: pytest.MonkeyPatch,
        operation: str,
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id, outcome, release, thread = self._blocked_work_turn(client, headers, monkeypatch)
        try:
            with database.transaction() as db:
                drawings_before = db.execute(
                    select(func.count())
                    .select_from(SceneObjectRow)
                    .where(
                        SceneObjectRow.learner_id == learner_id,
                        SceneObjectRow.author_role == "tutor",
                    )
                ).scalar_one()
            observation_id = self._work_observation(database, learner_id, session_id)
            if operation == "correct":
                response = client.post(
                    f"/memory/evidence/{observation_id}/correction",
                    json={"correct": True},
                    headers=headers,
                )
            else:
                response = client.delete(f"/memory/evidence/{observation_id}", headers=headers)
            assert response.status_code == 200, response.text
            invalidated = response.json()["effects"]["pending_turns_invalidated"]
            assert len(invalidated) == 1
        finally:
            release.set()
            thread.join(timeout=20)
        with database.transaction() as db:
            turn = db.get(TutorTurnRow, invalidated[0])
            assert turn is not None and turn.status == "superseded"
            tutor_hints = db.execute(
                select(func.count()).select_from(HintRow).where(HintRow.learner_id == learner_id)
            ).scalar_one()
            drawings = db.execute(
                select(func.count())
                .select_from(SceneObjectRow)
                .where(
                    SceneObjectRow.learner_id == learner_id, SceneObjectRow.author_role == "tutor"
                )
            ).scalar_one()
            assert tutor_hints == 0 and drawings == drawings_before
        late = outcome["response"]
        assert late.status_code == 200, late.text
        assert late.json()["status"] == "superseded"
        assert late.json()["utterance"] is None
        if operation == "delete":
            assert "2x + 3 = 14" not in json.dumps(late.json())

    def test_turn_in_a_deleted_session_cannot_commit(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id, outcome, release, thread = self._blocked_work_turn(client, headers, monkeypatch)
        try:
            assert client.delete(f"/sessions/{session_id}", headers=headers).status_code == 200
        finally:
            release.set()
            thread.join(timeout=20)
        late = outcome["response"]
        assert late.status_code == 409, late.text
        assert late.json()["error"]["code"] == "turn_removed"
        with database.transaction() as db:
            for model in (StepRow, ObservationRow, HintRow, SceneObjectRow, TutorTurnRow):
                count = db.execute(
                    select(func.count()).select_from(model).where(model.learner_id == learner_id)
                ).scalar_one()
                assert count == 0, model


class TestSessionAndProfileRemoval:
    def test_session_deletion_removes_scene_evidence_and_derived_content_only(
        self, client: TestClient, database: Database, ben: dict[str, str]
    ) -> None:
        learner_id = DEMO_LEARNER_BEN
        headers = ben
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        work = post_turn(
            client,
            headers,
            session_id,
            "work",
            {"expected_revision": 1, "text": "2x + 3 = 14"},
            key("rm"),
        )
        assert work.status_code == 200
        other_session = start_session(client, headers, "keep me")
        client.put(
            "/me/tutor-configuration",
            json={"appearance": "animal", "personality": "playful"},
            headers=headers,
        )
        with database.transaction() as db:
            before = learner_inventory(db, learner_id)
            curriculum = db.execute(select(func.count()).select_from(AssessmentRow)).scalar_one()
        assert before["steps"] >= 1 and before["scene_objects"] >= 1

        response = client.delete(f"/sessions/{session_id}", headers=headers)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["scope"] == "session" and receipt["before"]["steps"] >= 1
        assert receipt["after"]["steps"] == 0
        assert receipt["after"]["scene_objects"] == 0
        assert receipt["after"]["tutor_turns"] == 0
        assert receipt["tombstones_written"] >= 1
        assert "not secure disk" in receipt["notice"]

        assert client.get(f"/sessions/{session_id}/state", headers=headers).status_code == 404
        assert client.get(f"/sessions/{other_session}/state", headers=headers).status_code == 200
        assert client.get("/me", headers=headers).json()["tutor_configuration"]["appearance"] == (
            "animal"
        )
        with database.transaction() as db:
            assert (
                db.execute(select(func.count()).select_from(AssessmentRow)).scalar_one()
                <= curriculum
            )
        assert client.delete(f"/sessions/{session_id}", headers=headers).status_code == 404

    def test_session_deletion_follows_ids_into_other_sessions_and_recomputes(
        self, client: TestClient, database: Database, ada: dict[str, str]
    ) -> None:
        response = client.delete(f"/sessions/{ADA_SESSION}", headers=ada)
        assert response.status_code == 200, response.text
        assert response.json()["scope"] == "session"
        with database.transaction() as db:
            assert db.get(MisconceptionHypothesisRow, ADA_HYPOTHESIS) is None
            assert db.get(MemoryEntryRow, ADA_NOTE) is None
            assert db.get(ObservationRow, ADA_OBSERVATION) is None
            # Ada the learner and her other records (preference, config) remain.
            assert db.get(LearnerRow, DEMO_LEARNER_ADA) is not None
        assert client.get("/me", headers=ada).status_code == 200

    def test_profile_deletion_requires_confirmation(
        self, client: TestClient, ben: dict[str, str]
    ) -> None:
        assert client.delete("/me", headers=ben).status_code == 422
        assert client.delete("/me?confirm=yes", headers=ben).status_code == 422
        assert client.get("/me", headers=ben).status_code == 200

    def test_profile_deletion_revokes_tokens_and_preserves_others_and_curriculum(
        self,
        client: TestClient,
        database: Database,
        ada: dict[str, str],
        ben: dict[str, str],
        seeded_db_url: str,
    ) -> None:
        session_id = start_session(client, ben)
        check_in(client, ben, session_id)
        with database.transaction() as db:
            ada_before = learner_inventory(db, DEMO_LEARNER_ADA)
            concepts_before = db.execute(text_count("concepts")).scalar_one()
            edges_before = db.execute(text_count("prerequisite_edges")).scalar_one()

        response = client.delete("/me?confirm=delete-my-profile", headers=ben)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["scope"] == "profile"
        assert receipt["credentials_revoked"] >= 1
        assert receipt["before"]["learners"] == 1 and receipt["after"]["learners"] == 0
        assert all(count == 0 for count in receipt["after"].values())

        # Revoked credential: no record can be read, listed, corrected or deleted again.
        for method, path in [
            ("GET", "/me"),
            ("GET", "/sessions"),
            ("GET", f"/sessions/{session_id}/state"),
            ("GET", "/memory/inspect"),
            ("DELETE", f"/sessions/{session_id}"),
            ("DELETE", "/me?confirm=delete-my-profile"),
        ]:
            assert client.request(method, path, headers=ben).status_code == 401, path

        with database.transaction() as db:
            assert learner_inventory(db, DEMO_LEARNER_ADA) == ada_before
            assert db.execute(text_count("concepts")).scalar_one() == concepts_before
            assert db.execute(text_count("prerequisite_edges")).scalar_one() == edges_before
            assert db.get(LearnerRow, DEMO_LEARNER_BEN) is None
        assert client.get("/me", headers=ada).status_code == 200

        # No seed resurrection: reseeding in-process and from a fresh CLI keeps Ben gone.
        with database.transaction() as db:
            seed_database(db)
        run_cli(seeded_db_url, "seed")
        with database.transaction() as db:
            assert db.get(LearnerRow, DEMO_LEARNER_BEN) is None
            tombstone = db.execute(
                select(DeletionTombstoneRow).where(
                    DeletionTombstoneRow.record_id == DEMO_LEARNER_BEN
                )
            ).scalar_one()
            assert tombstone.record_kind == "learner"

    def test_bootstrapped_profile_deletion_leaves_nothing_behind(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client, "Temporary learner")
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        assert client.delete("/me?confirm=delete-my-profile", headers=headers).status_code == 200
        with database.transaction() as db:
            inventory = learner_inventory(db, learner_id)
        assert all(count == 0 for count in inventory.values())
        assert client.get("/me", headers=headers).status_code == 401


def text_count(table: str):
    return select(func.count()).select_from(Base.metadata.tables[table])


class TestTwoLearnerAuthorization:
    """Learner B can never see, correct, delete or learn the existence of learner A's records."""

    ROUTES: ClassVar[list[tuple[str, str, dict | None]]] = [
        ("GET", f"/memory/sources/{ADA_STEP}", None),
        ("POST", f"/memory/evidence/{ADA_OBSERVATION}/correction", {"correct": True}),
        ("DELETE", f"/memory/evidence/{ADA_OBSERVATION}", None),
        ("POST", f"/memory/notes/{ADA_NOTE}/correction", {"content": "Not yours."}),
        ("DELETE", f"/memory/notes/{ADA_NOTE}", None),
        ("DELETE", f"/memory/hypotheses/{ADA_HYPOTHESIS}", None),
        ("DELETE", f"/sessions/{ADA_SESSION}", None),
    ]

    @pytest.mark.parametrize(("method", "path", "body"), ROUTES)
    def test_foreign_ids_are_indistinguishable_from_missing_and_change_nothing(
        self,
        client: TestClient,
        database: Database,
        ada: dict[str, str],
        ben: dict[str, str],
        method: str,
        path: str,
        body: dict | None,
    ) -> None:
        with database.transaction() as db:
            ada_before = learner_inventory(db, DEMO_LEARNER_ADA)
            tombstones = db.execute(text_count("deletion_tombstones")).scalar_one()
            estimates = estimate(database, DEMO_LEARNER_ADA, DISTRIBUTION)
        foreign = client.request(method, path, json=body, headers=ben)
        missing_path = path.replace(ADA_STEP, "nope").replace(ADA_OBSERVATION, "nope")
        for original in (ADA_NOTE, ADA_HYPOTHESIS, ADA_SESSION):
            missing_path = missing_path.replace(original, "nope")
        missing = client.request(method, missing_path, json=body, headers=ben)
        assert foreign.status_code == 404
        assert foreign.json() == missing.json()
        assert client.request(method, path, json=body).status_code == 401
        with database.transaction() as db:
            assert learner_inventory(db, DEMO_LEARNER_ADA) == ada_before
            assert db.execute(text_count("deletion_tombstones")).scalar_one() == tombstones
        assert estimate(database, DEMO_LEARNER_ADA, DISTRIBUTION) == estimates
        assert client.get("/memory/inspect", headers=ada).status_code == 200

    def test_inspection_is_scoped_to_the_credential(
        self, client: TestClient, ada: dict[str, str], ben: dict[str, str]
    ) -> None:
        mine = client.get("/memory/inspect", headers=ada).json()
        theirs = client.get("/memory/inspect", headers=ben).json()
        assert mine["learner_id"] == DEMO_LEARNER_ADA
        assert theirs["learner_id"] == DEMO_LEARNER_BEN
        assert ADA_HYPOTHESIS in {i["id"] for i in mine["items"]}
        assert ADA_HYPOTHESIS not in json.dumps(theirs)
        assert client.get("/memory/inspect").status_code == 401

    def test_foreign_session_filter_cannot_widen_inspection(
        self, client: TestClient, ben: dict[str, str]
    ) -> None:
        response = client.get(f"/memory/inspect?session_id={ADA_SESSION}", headers=ben)
        assert response.status_code in (200, 404)
        assert ADA_HYPOTHESIS not in response.text and ADA_NOTE not in response.text

    def test_other_learners_deletion_leaves_ada_untouched(
        self, client: TestClient, database: Database, ada: dict[str, str], ben: dict[str, str]
    ) -> None:
        with database.transaction() as db:
            ada_before = learner_inventory(db, DEMO_LEARNER_ADA)
        assert client.delete("/me?confirm=delete-my-profile", headers=ben).status_code == 200
        with database.transaction() as db:
            assert learner_inventory(db, DEMO_LEARNER_ADA) == ada_before
            assert db.execute(text_count("deletion_tombstones")).scalar_one() == 1
        assert client.get("/me", headers=ada).status_code == 200
