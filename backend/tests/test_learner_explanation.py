"""Offline learner explanation: labeled fallback, no Factory or Daytona contact."""

import socket
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.interactives.fallback import DISTRIBUTION_FALLBACK, FALLBACK_LABEL, GROUPING_FALLBACK
from app.interactives.learner import LEARNER_NOTICE
from app.main import create_app
from app.schemas.interactives import LearnerExplanation

ENV_NAMES = (
    "TUTOR_ENV_FILE",
    "DATABASE_URL",
    "EXTERNAL_INTEGRATIONS_ENABLED",
    "FACTORY_INTERACTIVES_ENABLED",
    "FACTORY_DROID_EXECUTABLE",
    "FACTORY_MODEL",
    "DAYTONA_CHECKS_ENABLED",
    "DAYTONA_API_KEY",
    "DAYTONA_API_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def refuse_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the learner explanation path must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def client_for(tmp_path: Path, **overrides: object) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'isolated.db'}"
    settings = Settings(database_url=database_url, **overrides)  # type: ignore[arg-type]
    assert "data/tutor.db" not in settings.database_url
    return TestClient(create_app(settings))


def post(client: TestClient, **body: object) -> Any:
    payload = {
        "concept_id": "concept.distribution",
        "misconception": "Multiplies only the first term",
        "context_note": "",
    }
    payload.update(body)
    return client.post("/explanations/learner", json=payload)


def test_import_does_not_load_factory_or_daytona_sdks() -> None:
    loaded = {name.split(".")[0] for name in sys.modules}
    assert "droid_sdk" not in loaded
    assert "daytona" not in loaded


def test_disabled_release_is_labeled_fallback_for_the_requested_concept(tmp_path: Path) -> None:
    response = post(client_for(tmp_path), concept_id="concept.grouping")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "learner-explanation.v1"
    assert body["live_services_contacted"] is False
    assert body["notice"] == LEARNER_NOTICE
    release = body["release"]
    assert release["source"] == "prevetted_fallback"
    assert release["fallback_reason"] == "integration_disabled"
    assert release["label"] == FALLBACK_LABEL
    assert "not generated" in release["label"]
    assert release["factory_state"] == release["daytona_state"] == "disabled"
    assert release["spec"] == GROUPING_FALLBACK.model_dump(mode="json")
    assert release["sandbox_ids_created"] == release["sandbox_ids_deleted"] == []
    assert release["checks"] == []


def test_distribution_request_returns_the_distribution_fallback(tmp_path: Path) -> None:
    response = post(client_for(tmp_path))
    assert response.status_code == 200
    release = response.json()["release"]
    assert release["spec"] == DISTRIBUTION_FALLBACK.model_dump(mode="json")
    assert release["spec"]["manipulative"]["component"] == "distribution"


def test_preferred_component_selects_the_prevetted_spec(tmp_path: Path) -> None:
    response = post(
        client_for(tmp_path),
        concept_id="concept.distribution",
        preferred_component="grouping",
    )
    assert response.status_code == 200
    assert response.json()["release"]["spec"]["manipulative"]["component"] == "grouping"


def test_request_text_is_not_echoed(tmp_path: Path) -> None:
    response = post(client_for(tmp_path), misconception="<script>alert('leak-me')</script>")
    assert response.status_code == 200
    assert "leak-me" not in response.text


def test_unknown_concept_is_rejected(tmp_path: Path) -> None:
    response = post(client_for(tmp_path), concept_id="concept.other")
    assert response.status_code == 422


def test_configured_integrations_are_not_contacted(tmp_path: Path) -> None:
    executable = tmp_path / "droid"
    executable.write_text('#!/bin/sh\necho spawned >> "$(dirname "$0")/spawned"\n')
    executable.chmod(0o755)
    client = client_for(
        tmp_path,
        external_integrations_enabled=True,
        factory_interactives_enabled=True,
        factory_droid_executable=str(executable),
        factory_model="fixture-model",
        daytona_checks_enabled=True,
        daytona_api_key=SecretStr("test-daytona-key"),
        daytona_api_url="https://app.daytona.io/api",
    )
    response = post(client, concept_id="concept.grouping")
    assert response.status_code == 200
    body = response.json()
    assert body["live_services_contacted"] is False
    assert body["notice"] == LEARNER_NOTICE
    release = body["release"]
    assert release["source"] == "prevetted_fallback"
    assert release["fallback_reason"] == "checks_unavailable"
    assert release["label"] == FALLBACK_LABEL
    assert release["factory_state"] == release["daytona_state"] == "configured_unverified"
    assert release["sandbox_ids_created"] == release["sandbox_ids_deleted"] == []
    assert not (tmp_path / "spawned").exists()


def test_factory_without_daytona_stays_a_fallback_and_does_not_spawn(tmp_path: Path) -> None:
    executable = tmp_path / "droid"
    executable.write_text('#!/bin/sh\necho spawned >> "$(dirname "$0")/spawned"\n')
    executable.chmod(0o755)
    client = client_for(
        tmp_path,
        external_integrations_enabled=True,
        factory_interactives_enabled=True,
        factory_droid_executable=str(executable),
        factory_model="fixture-model",
        daytona_checks_enabled=False,
    )
    response = post(client)
    assert response.status_code == 200
    release = response.json()["release"]
    assert release["source"] == "prevetted_fallback"
    assert release["fallback_reason"] == "checks_unavailable"
    assert release["factory_state"] == "configured_unverified"
    assert release["daytona_state"] == "disabled"
    assert release["sandbox_ids_created"] == []
    assert not (tmp_path / "spawned").exists()


def test_contract_cannot_claim_a_live_call() -> None:
    with pytest.raises(ValidationError):
        LearnerExplanation.model_validate(
            {
                "schema_version": "learner-explanation.v1",
                "live_services_contacted": True,
                "notice": LEARNER_NOTICE,
                "release": {
                    "schema_version": "released-explanation.v1",
                    "source": "generated_verified",
                    "label": "Generated explanation that passed the app's own checks",
                    "spec": DISTRIBUTION_FALLBACK.model_dump(mode="json"),
                    "spec_digest": "a" * 64,
                    "fallback_reason": None,
                    "factory_state": "configured_unverified",
                    "daytona_state": "configured_unverified",
                    "sandbox_ids_created": ["sbx-1"],
                    "sandbox_ids_deleted": ["sbx-1"],
                    "created_at": "2026-10-18T00:00:00Z",
                },
            }
        )
