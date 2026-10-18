"""A question the learner brings is read by Claude and shown back on the board.

The model call is patched. These tests never contact Anthropic.
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.tutor.brought_question import BroughtQuestionError, parse_tutor_display, wrap_teaching
from tests.conftest import bootstrap
from tests.test_tutor_turns import check_in, key, post_turn, start_session


def test_parse_tutor_display_accepts_a_fenced_object() -> None:
    parsed = parse_tutor_display(
        '```json\n{"statement": "Solve 4x + 1 = 9", "teaching": "Subtract 1 first.", '
        '"next_step": "Write the next line."}\n```'
    )
    assert parsed.statement == "Solve 4x + 1 = 9"
    assert parsed.teaching == "Subtract 1 first."
    assert parsed.next_step == "Write the next line."
    assert wrap_teaching("one two three", width=7) == ["one two", "three"]


def test_mock_tutor_refuses_a_brought_question(client: TestClient) -> None:
    _, headers = bootstrap(client)
    session_id = start_session(client, headers)
    response = post_turn(
        client,
        headers,
        session_id,
        "check-in",
        {"expected_revision": 0, "question_text": "What is 2 + 2?"},
        key("q"),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tutor_not_configured"


def test_claude_shows_the_brought_question_and_the_next_note(
    monkeypatch: pytest.MonkeyPatch, seeded_db_url: str
) -> None:
    replies = iter(
        [
            json.dumps(
                {
                    "statement": "Solve 4x + 1 = 9",
                    "teaching": "Subtract 1 from both sides so 4x stands alone.",
                    "next_step": "Write the equation after you subtract 1.",
                    "equations": [{"text": "4x + 1 = 9", "highlight_term": "1"}],
                }
            ),
            json.dumps(
                {
                    "statement": "Solve 4x + 1 = 9",
                    "teaching": "4x = 8. Divide both sides by 4 next.",
                    "next_step": "Write what one x equals.",
                    "equations": [{"text": "4x = 8", "highlight_term": "4x"}],
                }
            ),
        ]
    )

    def fake_complete(settings: Settings, *, system: str, blocks: list[dict[str, object]]) -> str:
        del settings, system, blocks
        return next(replies)

    monkeypatch.setattr("app.tutor.brought_question.complete_tutoring", fake_complete)
    settings = Settings(
        database_url=seeded_db_url,
        tutor_provider="claude",
        external_integrations_enabled=True,
        anthropic_api_key=SecretStr("sk-test-not-a-real-key"),
        anthropic_model="claude-test",
    )
    with TestClient(create_app(settings)) as claude_client:
        _, headers = bootstrap(claude_client)
        session_id = start_session(claude_client, headers)
        image = base64.b64encode(b"tiny-picture").decode()
        opened = check_in(
            claude_client,
            headers,
            session_id,
            question_text="please help",
            question_image_media_type="image/png",
            question_image_base64=image,
            goal="learner_question",
        )
        assert opened["status"] == "committed"
        assert opened["current_problem"]["statement"] == "Solve 4x + 1 = 9"
        assert opened["current_problem"]["problem_id"].startswith("problem.lrn.")
        assert opened["utterance"] == "Subtract 1 from both sides so 4x stands alone."
        assert opened["expected_student_action"] == "Write the equation after you subtract 1."
        scene = claude_client.get(f"/sessions/{session_id}/scene", headers=headers)
        assert scene.status_code == 200, scene.text
        notes = [
            obj
            for obj in scene.json()["objects"]
            if obj["semantic_role"] == "teaching_note" and obj["deleted_at"] is None
        ]
        assert len(notes) == 1
        assert notes[0]["payload"]["text"] == opened["utterance"]
        equations = [obj for obj in scene.json()["objects"] if obj["kind"] == "add_math"]
        assert len(equations) == 1
        assert equations[0]["payload"]["text"] == "4x + 1 = 9"
        assert equations[0]["payload"]["highlight_term"] == "1"
        assert equations[0]["payload"]["color_role"] == "tutor"

        follow = post_turn(
            claude_client,
            headers,
            session_id,
            "work",
            {"expected_revision": opened["session_revision"], "text": "4x = 8"},
            key("work"),
        )
        assert follow.status_code == 200, follow.text
        body = follow.json()
        assert body["status"] == "committed"
        assert body["utterance"] == "4x = 8. Divide both sides by 4 next."
        assert body["current_problem"]["statement"] == "Solve 4x + 1 = 9"
        again = claude_client.get(f"/sessions/{session_id}/scene", headers=headers).json()
        visible = [
            obj
            for obj in again["objects"]
            if obj["semantic_role"] == "teaching_note" and obj["deleted_at"] is None
        ]
        assert [obj["payload"]["text"] for obj in visible] == [body["utterance"]]
        # New tutor work must not erase the first equation from this problem.
        math = [obj for obj in again["objects"] if obj["kind"] == "add_math"]
        assert {obj["payload"]["text"] for obj in math} == {"4x + 1 = 9", "4x = 8"}
        assert math[0]["payload"]["at"] != math[1]["payload"]["at"]


@pytest.mark.parametrize(
    "equations",
    [
        [{"text": "x = 2", "highlight_term": "missing"}],
        [{"text": "<script>"}],
        [{"text": "x = 2"}] * 3,
    ],
)
def test_brought_equations_reject_invalid_board_output(equations: object) -> None:
    with pytest.raises(BroughtQuestionError):
        parse_tutor_display(
            json.dumps(
                {
                    "statement": "Solve x + 1 = 3",
                    "teaching": "Try one step.",
                    "equations": equations,
                }
            )
        )


@pytest.mark.parametrize("change_during_hint", [False, True])
def test_hint_reads_saved_board_twice_and_passes_images_to_tutor(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db_url: str,
    change_during_hint: bool,
) -> None:
    vision_calls = []
    hint_blocks = []

    def complete(settings: Settings, *, system: str, blocks: list[dict[str, object]]) -> str:
        if "You transcribe handwritten" in system:
            vision_calls.append(blocks)
            return '{"text": "4x = 8", "legible": true}'
        if "The learner is still" in system:
            hint_blocks.extend(blocks)
            if change_during_hint:
                scene_now = client.get(f"/sessions/{session_id}/scene", headers=headers).json()
                response = client.post(
                    f"/sessions/{session_id}/scene/operations",
                    headers=headers,
                    json={
                        "operation_id": key("new-ink"),
                        "expected_scene_revision": scene_now["scene_revision"],
                        "action": {"op": "add_stroke", "points": [{"x": 180, "y": 400}]},
                    },
                )
                assert response.status_code == 200
        return json.dumps(
            {
                "statement": "Solve 4x + 1 = 9",
                "teaching": "What would undo multiplying by 4?",
                "next_step": "Try one operation.",
                "equations": [],
            }
        )

    monkeypatch.setattr("app.tutor.brought_question.complete_tutoring", complete)
    monkeypatch.setattr("app.whiteboard.reading.complete_tutoring", complete)
    settings = Settings(
        database_url=seeded_db_url,
        tutor_provider="claude",
        external_integrations_enabled=True,
        anthropic_api_key=SecretStr("test"),
        anthropic_model="test",
    )
    with TestClient(create_app(settings)) as client:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        opened = check_in(
            client, headers, session_id, question_text="Solve 4x + 1 = 9", goal="learner_question"
        )
        scene = client.get(f"/sessions/{session_id}/scene", headers=headers).json()
        saved = client.post(
            f"/sessions/{session_id}/scene/operations",
            headers=headers,
            json={
                "operation_id": key("saved-ink"),
                "expected_scene_revision": scene["scene_revision"],
                "action": {
                    "op": "add_stroke",
                    "points": [{"x": 80, "y": 300}, {"x": 140, "y": 330}],
                },
            },
        )
        assert saved.status_code == 200, saved.text
        hint = post_turn(
            client,
            headers,
            session_id,
            "help",
            {
                "expected_revision": opened["session_revision"],
                "learner_control": "give_hint",
            },
            key("board-hint"),
        )
        assert hint.status_code == 200, hint.text
        if change_during_hint:
            assert hint.json()["status"] == "rejected", hint.text
            assert hint.json()["rejections"][0]["code"] == "board_changed"
        else:
            assert hint.json()["status"] == "committed", hint.text
        assert len(vision_calls) == 2
        assert sum(block["type"] == "image" for block in hint_blocks) == 2
        assert "4x = 8" in str(hint_blocks[-1])
