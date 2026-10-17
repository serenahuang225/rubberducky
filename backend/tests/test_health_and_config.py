import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_NAMES = (
    "TUTOR_PROVIDER",
    "EXTERNAL_INTEGRATIONS_ENABLED",
    "DATABASE_URL",
    "TUTOR_CORS_ORIGINS",
    "TUTOR_LOCAL_MODEL_LOAD_ENABLED",
    "TUTOR_ENV_FILE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def client_for(**overrides: object) -> TestClient:
    return TestClient(create_app(Settings.model_validate(overrides)))


def test_health_reports_ok_with_aware_utc_time() -> None:
    response = client_for().get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "health.v1"
    parsed = datetime.fromisoformat(body["time_utc"])
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_default_model_readiness_is_labeled_mock() -> None:
    body = client_for().get("/health/model").json()
    assert body["provider"] == "mock"
    assert body["ready"] is True
    assert body["is_mock"] is True
    assert "mock" in body["label"].lower()


def test_transformers_loading_is_opt_in_and_never_loaded_at_startup() -> None:
    disabled = client_for(tutor_provider="transformers").get("/health/model").json()
    assert disabled["state"] == "disabled"
    assert disabled["ready"] is False
    assert disabled["model_id"] == "HuggingFaceTB/SmolLM2-135M-Instruct"

    enabled = client_for(
        tutor_provider="transformers", tutor_local_model_load_enabled=True
    ).get("/health/model")
    assert enabled.json()["state"] == "not_loaded"


@pytest.mark.parametrize("provider", ["claude", "endpoint"])
def test_remote_providers_stay_disabled_without_activation(provider: str) -> None:
    body = client_for(tutor_provider=provider).get("/health/model").json()
    assert body["state"] == "disabled"
    assert body["ready"] is False

    activated = client_for(tutor_provider=provider, external_integrations_enabled=True)
    assert activated.get("/health/model").json()["state"] == "unverified"


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"tutor_provider": "gpt-anything"})


def test_root_dotenv_file_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("TUTOR_PROVIDER=claude\n")
    monkeypatch.chdir(tmp_path)
    assert Settings().tutor_provider == "mock"


def test_explicit_env_file_can_be_opted_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import load_settings

    env_file = tmp_path / "tutor.env"
    env_file.write_text("TUTOR_PROVIDER=transformers\n")
    monkeypatch.setenv("TUTOR_ENV_FILE", str(env_file))
    assert load_settings().tutor_provider == "transformers"


def test_cors_allows_only_configured_web_origin() -> None:
    client = client_for()
    headers = {"Access-Control-Request-Method": "GET"}
    allowed = client.options("/health", headers={**headers, "Origin": "http://127.0.0.1:3101"})
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:3101"
    denied = client.options("/health", headers={**headers, "Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_importing_app_loads_no_model_or_provider_sdk() -> None:
    probe = (
        "import sys, app.main; "
        "heavy = {'torch', 'transformers', 'peft', 'anthropic', 'chalkcompute', "
        "'daytona', 'droid_sdk', 'livekit'}; "
        "print(','.join(sorted(heavy & {m.split('.')[0] for m in sys.modules})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout.strip() == ""
