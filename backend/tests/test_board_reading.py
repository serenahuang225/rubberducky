"""Board vision uses saved student ink and never sends tutor marks as handwriting."""

import struct
import zlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.schemas.learner import SceneObject
from app.schemas.scene import SceneSnapshot
from app.whiteboard.reading import HEIGHT, WIDTH, ink_png, ink_views, read_ink
from tests.conftest import bootstrap
from tests.test_tutor_turns import start_session


def snapshot(author: str = "student") -> SceneSnapshot:
    return SceneSnapshot.model_validate(
        {
            "session_id": "s1",
            "scene_revision": 1,
            "student_undo_available": True,
            "student_redo_available": False,
            "tutor_move_undo_available": False,
            "objects": [
                SceneObject.model_validate(
                    {
                        "id": "o1",
                        "learner_id": "l1",
                        "session_id": "s1",
                        "author_role": author,
                        "semantic_role": "work",
                        "kind": "path",
                        "provenance": "submitted",
                        "created_at": datetime(2026, 10, 18, tzinfo=UTC),
                        "payload": {"points": [{"x": 100, "y": 100}, {"x": 200, "y": 100}]},
                    }
                )
            ],
        }
    )


def test_ink_renders_as_a_real_png_without_tutor_marks() -> None:
    image = ink_png(snapshot())
    assert image is not None and image.startswith(b"\x89PNG\r\n\x1a\n")
    offset, compressed = 8, b""
    while offset < len(image):
        size = struct.unpack(">I", image[offset : offset + 4])[0]
        if image[offset + 4 : offset + 8] == b"IDAT":
            compressed += image[offset + 8 : offset + 8 + size]
        offset += size + 12
    pixels = zlib.decompress(compressed)
    width, height = struct.unpack(">II", image[16:24])
    assert width <= WIDTH and height <= HEIGHT
    assert width < WIDTH  # a short line is cropped and enlarged, not left tiny on a blank board
    assert len(pixels) == (width + 1) * height
    assert pixels[32 * (width + 1) + 1 + 100] == 0
    assert pixels[10 * (width + 1) + 1 + 10] == 255
    assert ink_png(snapshot("tutor")) is None


def test_uncertain_reading_is_not_marked_legible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.whiteboard.reading.complete_tutoring",
        lambda *a, **kw: '{"text": "x = 4?", "legible": false}',
    )
    assert read_ink(Settings(), snapshot()) == ("x = 4?", False)


def test_board_read_checks_scope_and_revision_before_vision(
    seeded_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_read(settings: Settings, scene: SceneSnapshot) -> tuple[str, bool]:
        calls.append(scene.scene_revision)
        return "x = 4", True

    monkeypatch.setattr("app.api.scene.read_ink", fake_read)
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
        url = f"/sessions/{session_id}/scene/read"
        assert client.post(url, json={"scene_revision": 0}).status_code == 401
        assert client.post(url, headers=headers, json={"scene_revision": 999}).status_code == 409
        assert calls == []
        response = client.post(url, headers=headers, json={"scene_revision": 0})
        assert response.status_code == 200, response.text
        assert response.json() == {
            "text": "x = 4",
            "legible": True,
            "boxed_answer": False,
            "scene_revision": 0,
        }
        assert calls == [0]


def test_latest_strokes_are_focused_even_above_older_work() -> None:
    scene = snapshot()
    older = scene.objects[0].model_copy(
        update={
            "id": "older",
            "created_at": scene.objects[0].created_at - timedelta(seconds=1),
            "payload": {"points": [{"x": 900, "y": 900}, {"x": 950, "y": 950}]},
        }
    )
    scene = scene.model_copy(update={"objects": [scene.objects[0], older]})
    overview, focused = ink_views(scene)
    assert struct.unpack(">II", focused[16:24]) == (464, 256)
    assert struct.unpack(">II", overview[16:24]) != (464, 256)


def test_unclear_reading_gets_one_second_look_and_fenced_json_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = iter(
        ['{"text": "x?", "legible": false}', '```json\n{"text": "x^2 = 9", "legible": true}\n```']
    )
    calls = []

    def complete(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        return next(replies)

    monkeypatch.setattr("app.whiteboard.reading.complete_tutoring", complete)
    assert read_ink(Settings(), snapshot()) == ("x^2 = 9", True)
    assert len(calls) == 2
    blocks = calls[0]["blocks"]
    assert sum(block["type"] == "image" for block in blocks) == 2


@pytest.mark.parametrize("text", ["x =", "3x +", "(x + 2", "x^", "x = ?"])
def test_partial_lines_are_not_auto_submitted_even_if_model_claims_legible(
    text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    monkeypatch.setattr(
        "app.whiteboard.reading.complete_tutoring",
        lambda *a, **kw: json.dumps({"text": text, "legible": True}),
    )
    assert read_ink(Settings(), snapshot()) == (text, False)


def test_verified_reading_requires_two_matching_independent_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = iter(['{"text": "3x = 12", "legible": true}', '{"text": "3x=12", "legible": true}'])
    calls = []

    def complete(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        return next(replies)

    monkeypatch.setattr("app.whiteboard.reading.complete_tutoring", complete)
    assert read_ink(Settings(), snapshot(), verify=True, whole_board=True) == ("3x=12", True)
    assert len(calls) == 2


def test_disagreeing_reads_are_not_treated_as_certain(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter(
        [
            '{"text": "x=1", "legible": true}',
            '{"text": "x=7", "legible": true}',
            '{"text": "x=9", "legible": true}',
        ]
    )
    monkeypatch.setattr("app.whiteboard.reading.complete_tutoring", lambda *a, **kw: next(replies))
    assert read_ink(Settings(), snapshot(), verify=True)[1] is False


def test_a_closed_box_around_student_work_is_an_answer_box() -> None:
    from app.whiteboard.reading import has_answer_box

    scene = snapshot()
    box = scene.objects[0].model_copy(
        update={
            "id": "box",
            "created_at": scene.objects[0].created_at + timedelta(seconds=1),
            "payload": {
                "points": [
                    {"x": 70, "y": 70},
                    {"x": 230, "y": 70},
                    {"x": 230, "y": 140},
                    {"x": 70, "y": 140},
                    {"x": 70, "y": 70},
                ]
            },
        }
    )
    assert has_answer_box(scene.model_copy(update={"objects": [*scene.objects, box]}))
    assert not has_answer_box(scene)
