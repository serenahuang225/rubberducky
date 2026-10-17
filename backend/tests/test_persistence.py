import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.config import Settings
from app.db.database import Database
from app.db.migrate import head_revision, upgrade_to_head
from app.db.models import AttemptRow, Base, ObservationRow, SessionRow
from app.db.seed import (
    DEMO_LEARNER_ADA,
    DEMO_LEARNER_BEN,
    FIXTURE_PROBLEM_ID,
    all_seed_records,
    seed_database,
    seed_uuid,
)
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
ADA_SESSION = seed_uuid("session:ada:1")
HEAD = "0005_tutor_turns"


def run_cli(url: str, *args: str) -> Any:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--database-url", url, *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def counts(database: Database) -> dict[str, int]:
    with database.transaction() as db:
        return {
            table.name: db.execute(select(func.count()).select_from(table)).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def test_migration_creates_head_and_repeat_upgrade_is_harmless(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'nested' / 'fresh.db'}"
    assert upgrade_to_head(url) == head_revision(url) == HEAD
    assert upgrade_to_head(url) == HEAD
    database = Database(url)
    try:
        tables = set(inspect(database.engine).get_table_names())
        assert {t.name for t in Base.metadata.sorted_tables} | {"alembic_version"} == tables
        with database.engine.connect() as connection:
            # The migration chain, not create_all, defines the schema: no drift from models.
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        database.dispose()


def test_foreign_keys_are_enabled_on_every_connection(database: Database) -> None:
    with database.engine.connect() as first, database.engine.connect() as second:
        assert first.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert second.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def _observation_row(**overrides: Any) -> ObservationRow:
    values: dict[str, Any] = {
        "id": "obs-new",
        "schema_version": "observation.v1",
        "learner_id": DEMO_LEARNER_ADA,
        "session_id": ADA_SESSION,
        "source_type": "step",
        "source_id": "step-x",
        "evidence_kind": "observed_work",
        "concept_id": None,
        "correct": None,
        "latency_ms": None,
        "confidence": 0.5,
        "assisted": False,
        "provenance": "submitted",
        "observed_at": NOW,
        "recorded_at": NOW,
    }
    values.update(overrides)
    return ObservationRow(**values)


def test_dangling_session_reference_is_rejected(database: Database) -> None:
    before = counts(database)
    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(_observation_row(session_id="no-such-session"))
    assert counts(database) == before


def test_cross_learner_session_reference_is_rejected_by_the_database(database: Database) -> None:
    before = counts(database)
    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(_observation_row(learner_id=DEMO_LEARNER_BEN, session_id=ADA_SESSION))
    assert counts(database) == before


def test_database_rejects_out_of_range_confidence(database: Database) -> None:
    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(_observation_row(confidence=1.5))


def test_naive_datetime_is_rejected_at_storage(database: Database) -> None:
    with pytest.raises(StatementError, match="naive datetime"), database.transaction() as db:
        db.add(_observation_row(observed_at=datetime(2026, 10, 2, 9, 30)))


def test_injected_failure_rolls_back_a_multi_record_write(database: Database) -> None:
    before = counts(database)
    with pytest.raises(RuntimeError, match="injected"), database.transaction() as db:
        db.add(
            SessionRow(
                id="s-new",
                schema_version="session.v1",
                learner_id=DEMO_LEARNER_ADA,
                status="active",
                goal=None,
                revision=0,
                provenance="submitted",
                started_at=NOW,
                ended_at=None,
            )
        )
        db.flush()
        db.add(
            AttemptRow(
                id="a-new",
                schema_version="attempt.v1",
                learner_id=DEMO_LEARNER_ADA,
                session_id="s-new",
                problem_id=FIXTURE_PROBLEM_ID,
                provenance="submitted",
                started_at=NOW,
                completed_at=None,
            )
        )
        db.flush()
        raise RuntimeError("injected failure after both writes")
    assert counts(database) == before


def test_partial_failure_in_a_later_record_rolls_back_earlier_records(
    database: Database,
) -> None:
    before = counts(database)
    with pytest.raises(IntegrityError), database.transaction() as db:
        db.add(_observation_row(id="obs-ok"))
        db.flush()
        db.add(_observation_row(id="obs-bad", session_id="missing"))
        db.flush()
    assert counts(database) == before


def test_seeding_is_idempotent(database: Database) -> None:
    before = counts(database)
    with database.transaction() as db:
        assert seed_database(db) == {}
    assert counts(database) == before


def test_subprocess_restart_preserves_records_ids_utc_and_provenance(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'restart.db'}"
    assert run_cli(url, "migrate")["database_revision"] == HEAD
    first_seed = run_cli(url, "seed")
    assert first_seed["inserted"]["learners"] == 2

    with TestClient(create_app(Settings(database_url=url))) as client:
        boot = client.post("/demo/bootstrap", json={"display_name": "Cam"}).json()
        headers = {"Authorization": f"Bearer {boot['access_token']}"}
        session = client.post("/sessions", json={"goal": "Try a new problem"}, headers=headers)
        assert session.status_code == 201
        submitted = session.json()
    learner_id = boot["learner"]["id"]

    # Restart: fresh interpreter processes re-open the same file.
    assert run_cli(url, "migrate")["database_revision"] == HEAD
    second_seed = run_cli(url, "seed")
    assert second_seed["inserted"] == {}
    assert second_seed["row_counts"]["sessions"] == first_seed["row_counts"]["sessions"] + 1
    assert second_seed["row_counts"]["learners"] == 3

    own = run_cli(url, "history", "--learner", learner_id)
    assert own["learner"]["provenance"] == "submitted"
    assert own["learner"]["is_fictional"] is True
    assert own["sessions"] == [submitted]
    assert submitted["provenance"] == "submitted"
    assert submitted["started_at"].endswith("Z")
    assert own["observations"] == []

    ada = run_cli(url, "history", "--learner", "ada")
    assert [s["id"] for s in ada["sessions"]] == [ADA_SESSION]
    assert all(s["provenance"] == "fictional_seed" for s in ada["sessions"])
    observation = next(
        o for o in ada["observations"] if o["id"] == seed_uuid("observation:ada:1:0")
    )
    assert observation["latency_ms"] is None
    assert observation["correct"] is False


DUMP_SCRIPT = """
import json, sys
from app.db.database import Database
from app.db.seed import _ROW_FOR, all_seed_records
database = Database(sys.argv[1])
out = []
with database.transaction() as db:
    for record in all_seed_records():
        row = db.get(_ROW_FOR[type(record)], record.id)
        out.append(type(record).model_validate(row).model_dump(mode="json"))
print(json.dumps(out))
"""


def test_every_seeded_entity_round_trips_through_a_new_process(seeded_db_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", DUMP_SCRIPT, seeded_db_url],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    expected = [record.model_dump(mode="json") for record in all_seed_records()]
    assert json.loads(result.stdout) == expected
