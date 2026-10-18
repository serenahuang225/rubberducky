"""The fictional Chalk, Droid, and Daytona walkthrough stays local and labeled."""

import json
import socket
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.demos.integrations import (
    DROID_SPEC,
    build_fictional_integration_demos,
)
from app.interactives import trusted_checks
from app.main import create_app
from app.tutoring_eval.candidates import fixture_candidate
from app.tutoring_eval.cases import build_fixture_cases
from app.tutoring_eval.replay import build_snapshots
from app.tutoring_eval.runner import evaluate_candidate


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the fictional demos must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_demos_are_labeled_and_match_the_local_rubric_and_checks() -> None:
    demos = build_fictional_integration_demos()
    assert demos.is_fictional is True
    assert demos.live_services_contacted is False
    assert demos.chalk.uploaded is False
    assert demos.chalk.trained_model_result is False
    assert demos.chalk.learning_gain_claim is False
    assert demos.chalk.dataset_name == "rubberducky-tutoring-replay"
    assert demos.droid.factory_contacted is False
    assert demos.droid.credits_spent == 0
    assert demos.daytona.sandbox_created is False
    assert demos.daytona.sandbox_id == "sbx-fictional-demo"

    snapshots = build_snapshots(build_fixture_cases())
    good = evaluate_candidate(fixture_candidate("good"), snapshots)
    shown = demos.chalk.candidates[0]
    assert shown.candidate_name == "fixture:good"
    assert shown.errors == good.errors == 0
    assert [item.dimension for item in shown.dimensions] == [
        item.dimension for item in good.dimensions
    ]
    assert shown.dimensions[0].mean == good.dimensions[0].mean
    assert shown.turns
    assert all(turn.reply for turn in shown.turns)
    leaky = demos.chalk.candidates[1]
    assert leaky.candidate_name == "fixture:leaky"
    assert leaky.turns == []

    def respect(candidate: object) -> float:
        dimensions = candidate.dimensions  # type: ignore[attr-defined]
        mean = next(item.mean for item in dimensions if item.dimension == "respect")
        assert mean is not None
        return mean

    assert respect(leaky) < respect(shown)

    report = trusted_checks.check_spec(DROID_SPEC.model_dump(mode="json"))
    assert demos.daytona.passed is True
    assert demos.daytona.spec_digest == report["spec_digest"]
    assert [check.name for check in demos.daytona.checks] == [
        item["name"] for item in report["checks"]
    ]
    assert "Factory" in demos.droid.notice
    blob = demos.model_dump_json()
    assert "sbx-created" not in blob
    assert "live_chalk" not in blob


def test_cli_prints_each_fictional_demo(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli import main
    from app.config import Settings

    monkeypatch.setattr("app.cli.get_settings", lambda: Settings(database_url="sqlite://"))
    assert main(["demo"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["is_fictional"] is True
    assert set(body) >= {"chalk", "droid", "daytona"}
    assert main(["demo", "daytona"]) == 0
    section = json.loads(capsys.readouterr().out)
    assert section["live_services_contacted"] is False
    assert section["daytona"]["sandbox_created"] is False


def test_route_returns_the_walkthrough_and_can_be_disabled() -> None:
    with TestClient(create_app(Settings(database_url="sqlite://"))) as client:
        response = client.get("/demo/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "fictional-integration-demos.v1"
    assert body["chalk"]["candidates"][0]["candidate_name"] == "fixture:good"
    assert body["droid"]["spec"]["manipulative"]["component"] == "distribution"

    disabled = Settings(database_url="sqlite://", demo_bootstrap_enabled=False)
    with TestClient(create_app(disabled)) as client:
        refused = client.get("/demo/integrations")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "bootstrap_disabled"
