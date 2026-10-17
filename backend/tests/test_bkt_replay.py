"""Replay from raw evidence in a migrated file-backed SQLite database, plus CLI and API."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.cli import main
from app.clock import utc_now
from app.db.database import Database
from app.db.models import BKTCountedOpportunityRow, MasteryEstimateRow, ObservationRow
from app.db.seed import DEMO_LEARNER_ADA, insert_missing, seed_uuid
from app.learner.pairing import issue_pairing_code
from app.tracing.contracts import DEFAULT_PARAMETERS, BKTParameters, BKTSnapshot
from app.tracing.fixtures import FIXTURE_CONCEPT_ID, FIXTURE_LEARNER_ID, bkt_fixture_records
from app.tracing.predictor import BKTPredictor
from app.tracing.replay import (
    ParameterConflictError,
    persisted_tracing,
    register_parameters,
    replay_learner,
)

TOL = 1e-12
NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
NO_LEARN = BKTParameters.model_validate(
    DEFAULT_PARAMETERS.model_dump()
    | {"parameter_version": "bkt-handset-no-learn.v1", "p_learn": 0.0, "description": "T=0"}
)


@pytest.fixture
def fixture_db(database: Database) -> Database:
    with database.transaction() as db:
        insert_missing(db, bkt_fixture_records())
    return database


def obs(name: str) -> str:
    return seed_uuid(f"observation:bkt-fixture:{name}")


def counts(database: Database) -> tuple[int, int, int]:
    with database.transaction() as db:
        return (
            db.execute(select(func.count()).select_from(ObservationRow)).scalar_one(),
            db.execute(select(func.count()).select_from(BKTCountedOpportunityRow)).scalar_one(),
            db.execute(select(func.count()).select_from(MasteryEstimateRow)).scalar_one(),
        )


def test_replay_counts_two_independent_opportunities(fixture_db: Database) -> None:
    with fixture_db.transaction() as db:
        _, report = replay_learner(db, FIXTURE_LEARNER_ID, NOW)
    statuses = {u.observation_id: (u.status, u.reason) for u in report.updates}
    assert statuses == {
        obs("first"): ("counted", None),
        obs("retry"): ("duplicate_opportunity", "opportunity already counted for this concept"),
        obs("revealed"): ("ineligible", "answer_revealed"),
        obs("tired"): ("ineligible", "no_concept"),
        obs("unsupported"): ("ineligible", "no_response_correctness"),
        obs("transfer"): ("counted", None),
    }
    counted = [u for u in report.updates if u.status == "counted"]
    assert abs((counted[0].p_known_after or 0) - 10 / 19) <= TOL
    assert abs((counted[1].p_known_after or 0) - 0.82) <= TOL
    assert report.counted_opportunities == 2
    assert report.metadata.parameter_version == "bkt-handset.v1"
    assert report.parameters.calibrated is False
    assert report.raw_event_ids == [u.observation_id for u in report.updates]


def test_repeat_and_restart_replay_is_deterministic(fixture_db: Database) -> None:
    raw_before = counts(fixture_db)[0]
    with fixture_db.transaction() as db:
        _, first = replay_learner(db, FIXTURE_LEARNER_ID, NOW)
    after_first = counts(fixture_db)
    with fixture_db.transaction() as db:
        _, repeat = replay_learner(db, FIXTURE_LEARNER_ID, NOW + timedelta(hours=1))
    assert repeat == first
    assert counts(fixture_db) == after_first
    assert after_first[0] == raw_before  # raw evidence never duplicated or rewritten

    restarted = Database(fixture_db.url)
    try:
        with restarted.transaction() as db:
            stored = persisted_tracing(db, FIXTURE_LEARNER_ID, "bkt-handset.v1")
            _, again = replay_learner(db, FIXTURE_LEARNER_ID, NOW + timedelta(days=1))
    finally:
        restarted.dispose()
    assert again == first
    assert [c.observation_id for c in stored.counted] == [obs("first"), obs("transfer")]
    assert [c.sequence for c in stored.counted] == [1, 2]
    assert all(c.eligibility_version == "bkt-eligibility.v1" for c in stored.counted)
    (estimate,) = stored.estimates
    assert estimate.concept_id == FIXTURE_CONCEPT_ID and estimate.calibrated is False
    assert abs(estimate.p_known - 0.82) <= TOL
    assert estimate.source_observation_ids == [obs("first"), obs("transfer")]
    assert estimate.provenance == "fictional_seed"


def test_new_parameter_version_recomputes_from_raw_history(fixture_db: Database) -> None:
    with fixture_db.transaction() as db:
        replay_learner(db, FIXTURE_LEARNER_ID, NOW)
        assert register_parameters(db, NO_LEARN, NOW) is True
        assert register_parameters(db, NO_LEARN, NOW) is False
        _, report = replay_learner(db, FIXTURE_LEARNER_ID, NOW, NO_LEARN.parameter_version)
    (estimate,) = report.estimates
    assert abs(estimate.p_known - 81 / 106) <= TOL
    with fixture_db.transaction() as db:
        original = persisted_tracing(db, FIXTURE_LEARNER_ID, "bkt-handset.v1")
        changed = persisted_tracing(db, FIXTURE_LEARNER_ID, NO_LEARN.parameter_version)
    assert abs(original.estimates[0].p_known - 0.82) <= TOL
    assert abs(changed.estimates[0].p_known - 81 / 106) <= TOL
    # Both versions start from p_init over the same raw IDs; neither reuses the other.
    assert changed.counted[0].p_known_before == original.counted[0].p_known_before == 0.2
    assert [c.observation_id for c in changed.counted] == [
        c.observation_id for c in original.counted
    ]


def test_parameter_versions_are_immutable(fixture_db: Database) -> None:
    with fixture_db.transaction() as db:
        register_parameters(db, NO_LEARN, NOW)
        with pytest.raises(ParameterConflictError):
            register_parameters(db, NO_LEARN.model_copy(update={"p_slip": 0.2}), NOW)


def test_seeded_assisted_history_never_counts(database: Database) -> None:
    with database.transaction() as db:
        _, report = replay_learner(db, DEMO_LEARNER_ADA, NOW, persist=False)
    assert report.counted_opportunities == 0
    assert {u.reason for u in report.updates} == {"not_verified_assessment"}


def test_cli_replay_state_and_parameter_change(
    seeded_db_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["--database-url", seeded_db_url, "tracing"]

    def run(*args: str) -> dict[str, object]:
        assert main([*base, *args]) == 0
        return json.loads(capsys.readouterr().out)

    assert run("fixture")["learner_id"] == FIXTURE_LEARNER_ID
    run("fixture")  # idempotent
    state_file = tmp_path / "state.json"
    first = run("replay", "--learner", "bkt-fixture", "--state-out", str(state_file))
    second = run("replay", "--learner", "bkt-fixture")
    estimates = first["estimates"]
    assert isinstance(estimates, list)
    assert abs(estimates[0]["p_known"] - 0.82) <= TOL
    assert first["updates"] == second["updates"]
    snapshot = BKTSnapshot.model_validate_json(state_file.read_text())
    assert abs(BKTPredictor.from_snapshot(snapshot).p_known(FIXTURE_CONCEPT_ID) - 0.82) <= TOL

    stored = run("state", "--learner", "bkt-fixture")
    assert len(stored["counted"]) == 2  # type: ignore[arg-type]
    run(
        "parameters",
        "add",
        "--parameter-version",
        "bkt-handset-no-learn.v1",
        "--p-init",
        "0.2",
        "--p-learn",
        "0",
        "--p-guess",
        "0.25",
        "--p-slip",
        "0.1",
        "--description",
        "No-learning comparison",
    )
    changed = run(
        "replay", "--learner", "bkt-fixture", "--parameter-version", "bkt-handset-no-learn.v1"
    )
    assert abs(changed["estimates"][0]["p_known"] - 81 / 106) <= TOL  # type: ignore[index]
    with pytest.raises(SystemExit):
        main(
            [
                *base,
                "parameters",
                "add",
                "--parameter-version",
                "bad.v1",
                "--p-init",
                "nan",
                "--p-learn",
                "0",
                "--p-guess",
                "0.25",
                "--p-slip",
                "0.1",
                "--description",
                "x",
            ]
        )
    capsys.readouterr()
    assert main([*base, "replay", "--learner", "bkt-fixture", "--format", "text"]) == 0
    text = capsys.readouterr().out
    assert "calibrated=False" in text and "p_known=0.820000000000" in text


def test_readiness_api_is_qualitative_and_separates_transfer(
    fixture_db: Database, client: TestClient
) -> None:
    with fixture_db.transaction() as db:
        code = issue_pairing_code(db, FIXTURE_LEARNER_ID, utc_now(), timedelta(minutes=5))
    token = client.post("/pairing/redeem", json={"code": code}).json()["access_token"]
    response = client.get("/tracing/readiness", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    (concept,) = response.json()["concepts"]
    assert concept["readiness"] == "strong_so_far"
    assert concept["independent_transfer"] == "independent_correct"
    assert concept["calibrated"] is False
    assert concept["counted_independent_opportunities"] == 2
    assert not any(isinstance(v, float) for v in concept.values())
    assert "uncalibrated" in concept["note"]
    before = counts(fixture_db)
    client.get("/tracing/readiness", headers={"Authorization": f"Bearer {token}"})
    assert counts(fixture_db) == before
    assert client.get("/tracing/readiness").status_code == 401
