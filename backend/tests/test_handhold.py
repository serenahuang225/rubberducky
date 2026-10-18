"""Handhold mode is how much help; the learner's controls decide when."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.pedagogy.handhold import (
    HOLD_TEACHING,
    followup_system,
    opening_system,
)
from tests.conftest import bootstrap
from tests.test_tutor_turns import check_in, key, post_turn, start_session


def test_each_duck_teaches_in_its_own_way() -> None:
    vincent = opening_system("balanced", "vincent")
    assert "what comes next" in vincent
    zeeshan = followup_system("hands_off", "none", "zeeshan")
    assert "until they ask" in zeeshan
    assert "be helpful" in zeeshan
    tony = followup_system("balanced", "none", "tony")
    assert "follow that line" in tony
    janelle = opening_system("guided", "janelle")
    assert "thought-provoking questions" in janelle
    mary = opening_system("hands_off", "mary")
    assert "Do not give a direct hint" in mary
    assert "where they are" in mary


def test_modes_separate_how_much_help_from_when() -> None:
    guided = opening_system("guided")
    assert "small first hint" in guided
    hands_off = followup_system("hands_off", "none")
    assert "How could you check whether that works?" in hands_off
    assert "Do not name the mistake" in hands_off
    assert "Good job!" in hands_off
    assert "still exploring" in hands_off
    asked = followup_system("balanced", "ask_question")
    assert "Ask me a question" in asked
    assert "examine one assumption" in asked
    hinted = followup_system("guided", "give_hint")
    assert "Give me a hint" in hinted
    assert "one small hint" in hinted


def _claude_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        tutor_provider="claude",
        external_integrations_enabled=True,
        anthropic_api_key=SecretStr("sk-test-not-a-real-key"),
        anthropic_model="claude-test",
    )


def test_still_exploring_waits_without_another_model_call(
    monkeypatch: pytest.MonkeyPatch, seeded_db_url: str
) -> None:
    calls = {"n": 0}

    def fake_complete(settings: Settings, *, system: str, blocks: list[dict[str, object]]) -> str:
        del settings, system, blocks
        calls["n"] += 1
        return json.dumps(
            {
                "statement": "Solve 4x + 1 = 9",
                "teaching": "Subtract 1 from both sides so 4x stands alone.",
                "next_step": "Write the equation after you subtract 1.",
            }
        )

    monkeypatch.setattr("app.tutor.brought_question.complete_tutoring", fake_complete)
    with TestClient(create_app(_claude_settings(seeded_db_url))) as client:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        opened = check_in(client, headers, session_id, question_text="Solve 4x + 1 = 9")
        held = post_turn(
            client,
            headers,
            session_id,
            "help",
            {
                "expected_revision": opened["session_revision"],
                "learner_control": "still_exploring",
                "handhold": "hands_off",
            },
            key("hold"),
        )
        assert held.status_code == 200, held.text
        body = held.json()
        assert body["utterance"] == HOLD_TEACHING
        assert body["hint_level"] == 0
        assert "neither corrects nor confirms" in body["decision_justification"]
        assert calls["n"] == 1

