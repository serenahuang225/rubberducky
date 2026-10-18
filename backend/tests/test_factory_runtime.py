"""The production Factory adapter against a stand-in ``droid`` subprocess.

``droid_sdk`` really spawns ``tests/fake_droid.py`` and speaks stream-jsonrpc with it, so the
adapter's tool/permission/cwd/environment constraints are read back from what the subprocess
received. This is a transport fixture: no Factory service, model or credit is involved.
"""

import asyncio
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from droid_sdk import ReasoningEffort
from pydantic import SecretStr

from app.config import Settings
from app.interactives.errors import InteractiveError
from app.interactives.factory_runtime import (
    ENVIRONMENT_ALLOWLIST,
    FactoryExplanationGenerator,
    FactoryRuntimeConfig,
    build_prompt,
    scrubbed_environment,
)
from app.interactives.fallback import DISTRIBUTION_FALLBACK, GROUPING_FALLBACK
from app.schemas.interactives import ExplanationRequest
from tests.fake_droid import install_fake_droid, read_records, write_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
CANARIES = {
    "DATABASE_URL": "sqlite:////canary/learners.db",
    "ANTHROPIC_API_KEY": "sk-ant-canary-0123456789abcdef",
    "DAYTONA_API_KEY": "dtn-canary-0123456789abcdef",
    "TUTOR_ENDPOINT_API_KEY": "sk-endpoint-canary-0123456789",
    "CHALK_CLIENT_SECRET": "chalk-canary-0123456789",
    "SPECTRUM_PROJECT_SECRET": "spectrum-canary-0123456789",
}


def good_output() -> dict[str, Any]:
    return {
        "spec": DISTRIBUTION_FALLBACK.model_dump(mode="json"),
        "self_check_notes": ["I checked this myself."],
    }


def request(**overrides: Any) -> ExplanationRequest:
    fields: dict[str, Any] = {
        "concept_id": "concept.distribution",
        "misconception": "Multiplies only the first term inside brackets",
        "context_note": "Ada wrote 3(x+2)=3x+2",
    }
    return ExplanationRequest(**{**fields, **overrides})


def config_for(executable: Path, **overrides: Any) -> FactoryRuntimeConfig:
    fields: dict[str, Any] = {
        "executable": executable,
        "model": "fixture-model",
        "reasoning_effort": ReasoningEffort.LOW,
        "timeout_seconds": 20.0,
        "max_prompt_chars": 4_000,
        "max_output_chars": 6_000,
        "max_credits": 5.0,
    }
    return FactoryRuntimeConfig(**{**fields, **overrides})


@pytest.fixture
def droid_dir(tmp_path: Path) -> Path:
    return tmp_path / "droid-bin"


@pytest.fixture
def canary_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in CANARIES.items():
        monkeypatch.setenv(name, value)
    yield


def run_generate(config: FactoryRuntimeConfig, req: ExplanationRequest) -> Any:
    return asyncio.run(FactoryExplanationGenerator(config).generate(req))


def requests_by_method(records: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    return [r["params"] for r in records if r.get("event") == "request" and r["method"] == method]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return not alive(pid)


def test_valid_candidate_comes_back_as_a_typed_spec(droid_dir: Path) -> None:
    exe = install_fake_droid(droid_dir, {"structured_output": good_output(), "credits": 0.2})
    candidate = run_generate(config_for(exe), request())
    assert candidate.generated.spec == DISTRIBUTION_FALLBACK
    assert candidate.generated.self_check_notes == ["I checked this myself."]
    assert candidate.factory_credits == pytest.approx(0.2)


def test_session_is_constrained_to_no_tools_no_permissions_and_an_empty_temp_cwd(
    droid_dir: Path,
) -> None:
    exe = install_fake_droid(droid_dir, {"structured_output": good_output()})
    run_generate(config_for(exe), request())
    records = read_records(droid_dir)
    start = next(r for r in records if r["event"] == "start")
    assert start["argv"][:5] == [
        "exec",
        "--input-format",
        "stream-jsonrpc",
        "--output-format",
        "stream-jsonrpc",
    ]
    (init,) = requests_by_method(records, "droid.initialize_session")
    assert init["restrictToolIds"] == []
    assert init["autoRejectPermissionRequests"] is True
    assert init["autonomyLevel"] == "off"
    assert init["interactionMode"] == "auto"
    assert init["disableBuiltinSkills"] is True
    assert not init.get("mcpServers")
    assert init["modelId"] == "fixture-model"
    assert "no tools" in init["systemPrompt"]
    cwd = Path(init["cwd"]).resolve()
    assert cwd.name.startswith("rubberducky-droid-")
    assert REPO_ROOT not in cwd.parents and cwd != REPO_ROOT
    # The working directory is removed afterwards and was empty when the session ran.
    assert not cwd.exists()
    assert Path(start["cwd"]).resolve() == cwd


def test_only_the_bounded_request_and_output_schema_are_sent(droid_dir: Path) -> None:
    exe = install_fake_droid(droid_dir, {"structured_output": good_output()})
    run_generate(config_for(exe), request())
    (message,) = requests_by_method(read_records(droid_dir), "droid.add_user_message")
    assert message["text"] == build_prompt(request())
    assert len(message["text"]) < 4_000
    assert "concept.distribution" in message["text"]
    schema = message["outputFormat"]["schema"]
    assert schema["type"] == "object"
    assert "spec" in schema["properties"]
    assert not message.get("images") and not message.get("files")


def test_app_secrets_never_reach_the_subprocess_environment(
    droid_dir: Path, canary_env: None
) -> None:
    exe = install_fake_droid(droid_dir, {"structured_output": good_output()})
    run_generate(config_for(exe), request())
    start = next(r for r in read_records(droid_dir) if r["event"] == "start")
    for name, value in CANARIES.items():
        assert start["env"].get(name, "") == "", name
        assert value not in "".join(start["env"].values())
    assert start["env"]["PATH"] == os.environ["PATH"]


def test_scrubbed_environment_blanks_everything_outside_the_allowlist() -> None:
    result = scrubbed_environment({"PATH": "/bin", "HOME": "/h", "SECRET_THING": "x", "FOO": "y"})
    assert result == {"SECRET_THING": "", "FOO": ""}
    assert "FACTORY_API_KEY" in ENVIRONMENT_ALLOWLIST
    assert "DATABASE_URL" not in ENVIRONMENT_ALLOWLIST


def test_prompt_redacts_secret_shaped_text_and_has_no_identifiers() -> None:
    req = request(context_note="key sk-abcdefghijklmnopqrstuvwxyz0123 in the note")
    prompt = build_prompt(req)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in prompt
    assert "learner" not in prompt.lower().replace("misconception", "")


@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        (
            {
                "structured_output": {
                    "spec": {
                        **GROUPING_FALLBACK.model_dump(mode="json"),
                        "manipulative": {"component": "webview", "url": "https://evil.example"},
                    }
                }
            },
            "invalid_candidate",
        ),
        ({"structured_output": {"nonsense": True}}, "invalid_candidate"),
        ({"structured_output": None}, "invalid_candidate"),
        (
            {
                "structured_output": {
                    "spec": {
                        **GROUPING_FALLBACK.model_dump(mode="json"),
                        "title": "<script>alert(1)</script>",
                    }
                }
            },
            "invalid_candidate",
        ),
        (
            {
                "structured_output": {
                    **good_output(),
                    "self_check_notes": ["x" * 150] * 5 + ["y" * 4_000],
                }
            },
            "oversize_candidate",
        ),
        ({"structured_output": good_output(), "credits": 99.0}, "cost_exceeded"),
        ({"structured_output": good_output(), "credits": None}, "cost_unverified"),
        ({"mode": "error_turn"}, "generation_failed"),
        ({"mode": "bad_reason"}, "generation_failed"),
        ({"mode": "crash_on_start"}, "generation_failed"),
    ],
)
def test_unsafe_or_failed_results_are_refused_with_a_stable_code(
    droid_dir: Path, scenario: dict[str, Any], code: str
) -> None:
    exe = install_fake_droid(droid_dir, scenario)
    with pytest.raises(InteractiveError) as caught:
        run_generate(config_for(exe, max_output_chars=2_000), request())
    assert caught.value.code == code
    # Only the code survives: no provider text, spec content or URL in the message.
    assert "evil.example" not in str(caught.value)
    assert "script" not in str(caught.value)
    for entry in read_records(droid_dir):
        if entry["event"] == "start":
            assert wait_dead(entry["pid"])


def test_a_reported_overrun_interrupts_the_run_before_it_finishes(droid_dir: Path) -> None:
    # The turn would hang forever after the update: only the mid-run check can end it.
    exe = install_fake_droid(droid_dir, {"mode": "hang_after_usage", "usage_updates": [0.5, 9.0]})
    started = time.monotonic()
    with pytest.raises(InteractiveError) as caught:
        run_generate(config_for(exe, max_credits=1.0, timeout_seconds=30), request())
    assert caught.value.code == "cost_exceeded"
    assert time.monotonic() - started < 15
    records = read_records(droid_dir)
    assert "droid.interrupt_session" in [r["method"] for r in records if r["event"] == "request"]
    start = next(r for r in records if r["event"] == "start")
    assert wait_dead(start["pid"])


def test_usage_within_the_limit_is_accepted_at_the_boundary(droid_dir: Path) -> None:
    exe = install_fake_droid(
        droid_dir,
        {"structured_output": good_output(), "usage_updates": [0.5, 1.0], "credits": 1.0},
    )
    candidate = run_generate(config_for(exe, max_credits=1.0), request())
    assert candidate.factory_credits == pytest.approx(1.0)


def test_missing_executable_fails_without_a_subprocess(tmp_path: Path) -> None:
    with pytest.raises(InteractiveError) as caught:
        run_generate(config_for(tmp_path / "no-such-droid"), request())
    assert caught.value.code == "generation_failed"


def test_deadline_stops_a_hung_droid_and_terminates_the_subprocess(droid_dir: Path) -> None:
    exe = install_fake_droid(droid_dir, {"mode": "hang"})
    started = time.monotonic()
    with pytest.raises(InteractiveError) as caught:
        run_generate(config_for(exe, timeout_seconds=0.6), request())
    assert caught.value.code == "generation_timeout"
    assert time.monotonic() - started < 15
    start = next(r for r in read_records(droid_dir) if r["event"] == "start")
    assert wait_dead(start["pid"])


def test_cancel_interrupts_the_session_and_terminates_the_subprocess(droid_dir: Path) -> None:
    exe = install_fake_droid(droid_dir, {"mode": "hang"})

    async def scenario() -> None:
        task = asyncio.create_task(
            FactoryExplanationGenerator(config_for(exe, timeout_seconds=30)).generate(request())
        )
        deadline = time.monotonic() + 10
        while not requests_by_method(read_records(droid_dir), "droid.add_user_message"):
            assert time.monotonic() < deadline, "the turn never started"
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    records = read_records(droid_dir)
    start = next(r for r in records if r["event"] == "start")
    assert wait_dead(start["pid"])
    methods = [r["method"] for r in records if r["event"] == "request"]
    assert "droid.interrupt_session" in methods
    (init,) = requests_by_method(records, "droid.initialize_session")
    assert not Path(init["cwd"]).exists()


def test_construction_starts_nothing(droid_dir: Path) -> None:
    exe = install_fake_droid(droid_dir, {"structured_output": good_output()})
    FactoryExplanationGenerator(config_for(exe))
    assert read_records(droid_dir) == []


def test_config_from_settings_needs_an_explicit_executable_and_model() -> None:
    with pytest.raises(InteractiveError) as caught:
        FactoryRuntimeConfig.from_settings(Settings(factory_interactives_enabled=True))
    assert caught.value.code == "not_configured"
    config = FactoryRuntimeConfig.from_settings(
        Settings(
            factory_droid_executable="/opt/droid",
            factory_model="m",
            factory_api_key=SecretStr("k-secret-value"),
        )
    )
    assert config.executable == Path("/opt/droid") and config.api_key == "k-secret-value"


def test_rerunning_after_a_scenario_change_uses_a_fresh_subprocess(droid_dir: Path) -> None:
    exe = install_fake_droid(droid_dir, {"structured_output": good_output()})
    run_generate(config_for(exe), request())
    write_scenario(droid_dir, {"mode": "error_turn"})
    with pytest.raises(InteractiveError):
        run_generate(config_for(exe), request())
    starts = [r for r in read_records(droid_dir) if r["event"] == "start"]
    assert len({s["pid"] for s in starts}) == 2
