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
from app.tutor.brought_question import parse_tutor_display
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


def test_parse_keeps_the_approach_the_contradiction_and_the_explanation() -> None:
    parsed = parse_tutor_display(
        json.dumps(
            {
                "statement": "Solve 4x + 1 = 9",
                "teaching": "How could you check whether subtracting from one side works?",
                "next_step": "Try a check.",
                "approach": "subtract from one side only",
                "contradiction": "the other side stayed the same",
                "explained_failure": True,
            }
        )
    )
    assert parsed.approach == "subtract from one side only"
    assert parsed.contradiction == "the other side stayed the same"
    assert parsed.explained_failure is True


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


def test_a_wrong_approach_is_kept_with_what_contradicted_it(
    monkeypatch: pytest.MonkeyPatch, seeded_db_url: str
) -> None:
    replies = iter(
        [
            json.dumps(
                {
                    "statement": "Solve 4x + 1 = 9",
                    "teaching": "Try your own first step.",
                    "next_step": "Write a step.",
                }
            ),
            json.dumps(
                {
                    "statement": "Solve 4x + 1 = 9",
                    "teaching": "How could you check whether that works?",
                    "next_step": "Check both sides.",
                    "approach": "subtract from one side only",
                    "contradiction": "the other side stayed the same",
                    "explained_failure": True,
                }
            ),
        ]
    )

    seen: list[str] = []

    def fake_complete(settings: Settings, *, system: str, blocks: list[dict[str, object]]) -> str:
        del settings, blocks
        seen.append(system)
        return next(replies)

    monkeypatch.setattr("app.tutor.brought_question.complete_tutoring", fake_complete)
    with TestClient(create_app(_claude_settings(seeded_db_url))) as client:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        opened = check_in(
            client,
            headers,
            session_id,
            question_text="Solve 4x + 1 = 9",
            goal="learner_question",
        )
        # The opening call uses the check-in handhold. The follow-up must be hands off.
        follow = post_turn(
            client,
            headers,
            session_id,
            "work",
            {
                "expected_revision": opened["session_revision"],
                "text": "4x = 10",
                "handhold": "hands_off",
            },
            key("approach"),
        )
        assert follow.status_code == 200, follow.text
        body = follow.json()
        assert body["utterance"] == "How could you check whether that works?"
        assert body["approach_trace"] == {
            "schema_version": "approach-trace.v1",
            "approach": "subtract from one side only",
            "contradiction": "the other side stayed the same",
            "explained_failure": True,
        }
        assert body["hypothesis"]["label"] == "subtract from one side only"
        assert body["hypothesis"]["status"] == "contradicted"
        assert body["hypothesis"]["contradicting_source_ids"]
        assert "Mode: hands off" in seen[1]
        assert "How could you check whether that works?" in seen[1]
