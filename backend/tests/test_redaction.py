"""Canary tests for the shared redaction path (VAL-REL-004).

Canaries are random per run and are never printed: failures name the surface that leaked,
not the value. Surfaces covered: log records (including exception text), provider-failure and
validation error bodies, a synthetic optional-integration envelope, media events (including
inline image data), the SQLite file, and the built/public client assets.
"""

import base64
import logging
import re
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.errors import error_body
from app.config import Settings
from app.inference.errors import ProviderUnavailableError
from app.main import create_app
from app.redaction import (
    install_log_redaction,
    redact_text,
    redact_value,
    register_secrets,
)
from tests.conftest import bootstrap

REPO = Path(__file__).resolve().parents[2]


def _canary(prefix: str = "canary") -> str:
    return f"{prefix}-{secrets.token_hex(12)}"


def _assert_absent(canary: str, surface: str, haystack: str | bytes) -> None:
    needle: str | bytes = canary if isinstance(haystack, str) else canary.encode()
    if needle in haystack:
        pytest.fail(f"canary leaked through {surface}")


@pytest.fixture
def keyed_client(seeded_db_url: str) -> Iterator[tuple[TestClient, str]]:
    key = _canary("providerkey")
    settings = Settings(database_url=seeded_db_url, anthropic_api_key=SecretStr(key))
    with TestClient(create_app(settings)) as client:
        yield client, key


def test_text_patterns_remove_tokens_keys_and_inline_media() -> None:
    bearer = secrets.token_hex(16)
    pairing = "rdk_" + secrets.token_urlsafe(24)
    vendor = "sk-" + secrets.token_hex(16)
    assigned = secrets.token_hex(8)
    pixels = base64.b64encode(secrets.token_bytes(120)).decode()
    text = (
        f"Authorization: Bearer {bearer}; pairing {pairing}; key {vendor}; "
        f"api_key={assigned}; data:image/png;base64,{pixels}"
    )
    cleaned = redact_text(text)
    for value in (bearer, pairing, vendor, assigned, pixels):
        _assert_absent(value, "redact_text", cleaned)
    assert redact_text("2(x + 3) = 14") == "2(x + 3) = 14"


def test_value_redaction_hides_sensitive_keys_and_bytes() -> None:
    secret = _canary()
    cleaned = redact_value(
        {
            "headers": {"Authorization": f"Bearer {secret}"},
            "image_base64": secret,
            "nested": [{"api_key": secret}, b"\x00\x01"],
            "ok": "fine",
        }
    )
    _assert_absent(secret, "redact_value", repr(cleaned))
    assert cleaned["ok"] == "fine"


def test_log_records_are_redacted_including_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = _canary("logsecret")
    register_secrets([secret])
    install_log_redaction()
    logger = logging.getLogger("app.test_redaction")
    with caplog.at_level(logging.DEBUG, logger="app.test_redaction"):
        logger.warning("provider rejected %s", secret)
        try:
            raise RuntimeError(f"upstream echoed {secret}")
        except RuntimeError:
            logger.exception("call failed with key=%s", secret)
    _assert_absent(secret, "log message", caplog.text)
    _assert_absent(secret, "log record fields", repr([r.__dict__ for r in caplog.records]))


def test_provider_failure_envelope_never_echoes_the_provider_secret(
    keyed_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, key = keyed_client
    _, headers = bootstrap(client)
    session = client.post("/sessions", json={}, headers=headers).json()

    def failing(*_args: object, **_kwargs: object) -> None:
        raise ProviderUnavailableError("claude", f"upstream said the key {key} was rejected")

    monkeypatch.setattr("app.api.tutor.execute_turn", failing)
    response = client.post(
        f"/sessions/{session['id']}/check-in",
        json={"expected_revision": session["revision"], "energy": "ready"},
        headers={**headers, "Idempotency-Key": "provider-failure-0001"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    _assert_absent(key, "provider error envelope", response.text)


def test_validation_errors_use_the_envelope_and_do_not_echo_submitted_input(
    keyed_client: tuple[TestClient, str],
) -> None:
    client, _ = keyed_client
    _, headers = bootstrap(client)
    leaked_value = _canary("typedvalue")
    leaked_key = _canary("extrakey")
    response = client.post(
        "/sessions", json={"goal": 12, leaked_key: leaked_value}, headers=headers
    )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_version"] == "error.v1"
    assert body["error"]["code"] == "validation_error"
    fields = body["error"]["fields"]
    assert fields and all({"loc", "type", "message"} <= set(item) for item in fields)
    assert any(item["loc"][-1] == "goal" for item in fields)
    _assert_absent(leaked_value, "422 body", response.text)
    assert "input" not in {name for item in fields for name in item}
    docs = client.get("/openapi.json").json()
    schema = docs["paths"]["/sessions"]["post"]["responses"]["422"]["content"]["application/json"]
    assert schema["schema"]["$ref"].endswith("/ErrorEnvelope")


def test_malformed_json_and_query_errors_also_stay_in_the_envelope(
    keyed_client: tuple[TestClient, str],
) -> None:
    client, _ = keyed_client
    _, headers = bootstrap(client)
    bad = client.get("/memory/inspect?limit=0", headers=headers)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    garbled = client.post(
        "/sessions", content=b'{"goal": ', headers={**headers, "Content-Type": "application/json"}
    )
    assert garbled.status_code == 422
    assert garbled.json()["schema_version"] == "error.v1"


def test_synthetic_integration_failure_envelope_uses_the_shared_redaction() -> None:
    secret = _canary("integrationsecret")
    register_secrets([secret])
    media = base64.b64encode(secrets.token_bytes(300)).decode()
    body = error_body(
        "integration_failed",
        f"spectrum returned 401 for Bearer {secret}; payload {media}; project_secret={secret}",
    )
    text = repr(body)
    _assert_absent(secret, "integration failure envelope", text)
    _assert_absent(media, "integration failure envelope media", text)
    assert body["schema_version"] == "error.v1" and body["error"]["code"] == "integration_failed"


def test_media_event_canaries_stay_out_of_logs_responses_and_the_database(
    keyed_client: tuple[TestClient, str],
    seeded_db_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = keyed_client
    _, headers = bootstrap(client)
    session = client.post("/sessions", json={}, headers=headers).json()
    spoken = _canary("spokenwords")
    pixels = _canary("pixeldata")
    inline = base64.b64encode((pixels * 40).encode()).decode()
    url = f"/sessions/{session['id']}/media/events"
    base = {
        "schema_version": "media-event-request.v1",
        "expected_revision": session["revision"],
        "observed_epoch": 0,
        "source": "simulated",
    }
    with caplog.at_level(logging.DEBUG):
        voice = client.post(
            url,
            json={
                **base,
                "kind": "transcript",
                "event_id": "canary-voice-0001",
                "utterance_id": "u1",
                "sequence": 0,
                "phase": "final",
                "text": spoken,
            },
            headers=headers,
        )
        image = client.post(
            url,
            json={
                **base,
                "kind": "image_snapshot",
                "event_id": "canary-image-0001",
                "orientation": "work_facing",
                "trigger": "explicit_capture",
                "mime": "image/jpeg",
                "width": 64,
                "height": 64,
                "byte_size": 1_000,
                "image_base64": inline,
            },
            headers=headers,
        )
        oversized = client.post(
            url,
            json={
                **base,
                "kind": "image_snapshot",
                "event_id": "canary-image-0002",
                "orientation": "work_facing",
                "trigger": "explicit_capture",
                "mime": "image/jpeg",
                "width": 64,
                "height": 64,
                "byte_size": 99_999_999,
                "image_base64": inline,
            },
            headers=headers,
        )
    assert voice.status_code == image.status_code == 200
    assert oversized.status_code == 422
    for name, text in (("voice response", voice.text), ("image response", image.text)):
        _assert_absent(spoken, name, text)
        _assert_absent(pixels, name, text)
        _assert_absent(inline, name, text)
    _assert_absent(inline, "rejected media error body", oversized.text)
    _assert_absent(spoken, "logs", caplog.text)
    _assert_absent(pixels, "logs", caplog.text)
    db_bytes = Path(seeded_db_url.removeprefix("sqlite:///")).read_bytes()
    for canary in (spoken, pixels, inline):
        _assert_absent(canary, "sqlite file", db_bytes)


def test_server_secret_stays_out_of_turn_records_logs_and_the_database(
    keyed_client: tuple[TestClient, str],
    seeded_db_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, key = keyed_client
    _, headers = bootstrap(client)
    session = client.post("/sessions", json={}, headers=headers).json()
    with caplog.at_level(logging.DEBUG):
        turn = client.post(
            f"/sessions/{session['id']}/check-in",
            json={"expected_revision": session["revision"], "energy": "ready"},
            headers={**headers, "Idempotency-Key": "canary-turn-0001"},
        )
        status = client.get("/health/model")
    assert turn.status_code == 200, turn.text
    for name, text in (
        ("turn response", turn.text),
        ("model readiness", status.text),
        ("logs", caplog.text),
    ):
        _assert_absent(key, name, text)
    _assert_absent(key, "sqlite file", Path(seeded_db_url.removeprefix("sqlite:///")).read_bytes())


def test_public_client_assets_and_config_contain_no_secrets() -> None:
    secret_like = re.compile(
        r"sk-ant-[A-Za-z0-9_-]{8,}|rdk_[A-Za-z0-9_-]{24,}|-----BEGIN [A-Z ]*KEY"
    )
    public_names = re.compile(r"EXPO_PUBLIC_[A-Z0-9_]*(KEY|SECRET|TOKEN|PASSWORD)")
    scanned = 0
    roots = [
        REPO / "frontend" / "src",
        REPO / "frontend" / "App.tsx",
        REPO / "frontend" / "app.json",
    ]
    dist = REPO / "frontend" / "dist"
    if dist.exists():
        roots.append(dist)
    files: list[Path] = []
    for root in roots:
        files.extend([root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()])
    for path in files:
        if path.suffix in {".png", ".jpg", ".ttf", ".ico", ".woff", ".woff2"}:
            continue
        text = path.read_text(errors="ignore")
        scanned += 1
        if secret_like.search(text):
            pytest.fail(f"secret-like value in public asset {path.relative_to(REPO)}")
        if public_names.search(text):
            pytest.fail(f"secret-named public variable in {path.relative_to(REPO)}")
    example = REPO / ".env.example"
    if example.exists():
        for line in example.read_text().splitlines():
            if line.startswith("EXPO_PUBLIC_") and re.search(r"KEY|SECRET|TOKEN", line):
                pytest.fail("secret-named EXPO_PUBLIC variable in .env.example")
    assert scanned > 0
