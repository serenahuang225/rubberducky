"""Durable scene operations: student strokes, author-safe history, replay and scoping.

The student commits one operation per finished stroke through the real API. Operations are
idempotent by client-chosen operation ID and optimistic-concurrency checked against a
monotonic per-session scene revision. Student undo/redo and grouped tutor-move undo are
independent histories over one durable operation log; erased/undone objects stay hidden
across a database restart, and tutor-authored objects never become student evidence.
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import Database
from app.db.models import ObservationRow, SceneObjectRow
from app.whiteboard.geometry import BOARD_HEIGHT, BOARD_WIDTH, MAX_PATH_POINTS, PEN_WIDTH
from tests.conftest import bootstrap

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def start_session(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/sessions", json={"goal": "Practice"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def snapshot(client: TestClient, headers: dict[str, str], session_id: str) -> dict:
    response = client.get(f"/sessions/{session_id}/scene", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def operations(
    client: TestClient, headers: dict[str, str], session_id: str, after_seq: int = 0
) -> dict:
    response = client.get(
        f"/sessions/{session_id}/scene/operations",
        params={"after_seq": after_seq},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def commit(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    operation_id: str,
    expected: int,
    action: dict,
) -> dict:
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={
            "schema_version": "scene-operation-request.v1",
            "operation_id": operation_id,
            "expected_scene_revision": expected,
            "action": action,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def stroke(seed: float = 10.0) -> dict:
    return {
        "op": "add_stroke",
        "points": [
            {"x": seed, "y": seed},
            {"x": seed + 40.0, "y": seed + 20.0},
            {"x": seed + 80.0, "y": seed + 60.0},
        ],
    }


def visible_ids(scene: dict) -> list[str]:
    return [obj["id"] for obj in scene["objects"]]


def turn_key(name: str) -> str:
    return f"turn-{name}-0123456789"


def check_in(client: TestClient, headers: dict[str, str], session_id: str) -> dict:
    response = client.post(
        f"/sessions/{session_id}/check-in",
        json={"expected_revision": 0},
        headers={**headers, "Idempotency-Key": turn_key("ci")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_partial_distribution(
    client: TestClient, headers: dict[str, str], session_id: str
) -> dict:
    """The distribution fixture error: earns a grounded hint with two tutor drawings."""
    response = client.post(
        f"/sessions/{session_id}/work",
        json={"expected_revision": 1, "text": "2x + 3 = 14"},
        headers={**headers, "Idempotency-Key": turn_key("work")},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "committed"
    assert result["action_type"] == "diagnostic_hint"
    assert len(result["drawings"]) == 2
    return result


@pytest.fixture
def board(client: TestClient) -> tuple[TestClient, dict[str, str], str]:
    _, headers = bootstrap(client, "Scene learner")
    return client, headers, start_session(client, headers)


def test_committed_stroke_is_durable_and_visible(
    board: tuple[TestClient, dict[str, str], str], database: Database
) -> None:
    client, headers, session_id = board
    scene = snapshot(client, headers, session_id)
    assert scene["scene_revision"] == 0
    assert scene["objects"] == []
    assert scene["board_width"] == BOARD_WIDTH
    assert scene["board_height"] == BOARD_HEIGHT
    assert scene["pen_width"] == PEN_WIDTH

    result = commit(client, headers, session_id, "op-stroke-1", 0, stroke())
    assert result["replayed"] is False
    assert result["scene_revision"] == 1
    assert result["kind"] == "add_object"
    assert result["author_role"] == "student"
    object_id = result["object_id"]

    scene = snapshot(client, headers, session_id)
    assert scene["scene_revision"] == 1
    assert visible_ids(scene) == [object_id]
    (obj,) = scene["objects"]
    assert obj["author_role"] == "student"
    assert obj["semantic_role"] == "work"
    assert obj["kind"] == "path"
    assert obj["payload"]["width"] == PEN_WIDTH
    assert obj["payload"]["color_role"] == "student"
    assert len(obj["payload"]["points"]) == 3
    assert obj["teaching_step_id"] is None

    with database.transaction() as db:
        row = db.get(SceneObjectRow, object_id)
        assert row is not None
        assert row.author_role == "student"
        assert row.session_id == session_id
        assert row.deleted_at is None


def test_dot_stroke_is_a_single_point(board: tuple[TestClient, dict[str, str], str]) -> None:
    client, headers, session_id = board
    result = commit(
        client, headers, session_id, "op-dot", 0, {"op": "add_stroke", "points": [{"x": 5, "y": 5}]}
    )
    assert result["scene_revision"] == 1
    scene = snapshot(client, headers, session_id)
    assert scene["objects"][0]["payload"]["points"] == [{"x": 5.0, "y": 5.0}]


def test_retry_with_same_operation_id_replays_without_duplicates(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    first = commit(client, headers, session_id, "op-retry", 0, stroke())
    # A client whose response was lost retries the identical operation.
    second = commit(client, headers, session_id, "op-retry", 0, stroke())
    assert second["replayed"] is True
    assert second["object_id"] == first["object_id"]
    assert second["scene_revision"] == first["scene_revision"]
    scene = snapshot(client, headers, session_id)
    assert visible_ids(scene) == [first["object_id"]]
    assert scene["scene_revision"] == 1
    feed = operations(client, headers, session_id)
    assert len(feed["operations"]) == 1


def test_same_operation_id_with_different_content_conflicts(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    commit(client, headers, session_id, "op-conflict", 0, stroke())
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={
            "operation_id": "op-conflict",
            "expected_scene_revision": 1,
            "action": stroke(400.0),
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert len(snapshot(client, headers, session_id)["objects"]) == 1


def test_stale_scene_revision_conflicts(board: tuple[TestClient, dict[str, str], str]) -> None:
    client, headers, session_id = board
    commit(client, headers, session_id, "op-a", 0, stroke())
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={"operation_id": "op-b", "expected_scene_revision": 0, "action": stroke(300.0)},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "revision_conflict"
    assert "1" in response.json()["error"]["message"]
    # The rejected command changed nothing.
    scene = snapshot(client, headers, session_id)
    assert scene["scene_revision"] == 1
    assert len(scene["objects"]) == 1


def test_stroke_payload_bounds(board: tuple[TestClient, dict[str, str], str]) -> None:
    client, headers, session_id = board
    bad_payloads = [
        {"op": "add_stroke", "points": []},
        {"op": "add_stroke", "points": [{"x": -1, "y": 5}, {"x": 6, "y": 6}]},
        {"op": "add_stroke", "points": [{"x": 5, "y": 5}, {"x": BOARD_WIDTH + 1, "y": 6}]},
        {
            "op": "add_stroke",
            "points": [{"x": float(i), "y": float(i)} for i in range(MAX_PATH_POINTS + 1)],
        },
        {"op": "add_stroke", "points": [{"x": 1, "y": 1}, {"x": 2, "y": 2}], "color": "red"},
        {"op": "draw_shape", "shape": "circle", "start": {"x": 1, "y": 1}, "end": {"x": 9, "y": 9}},
    ]
    for index, action in enumerate(bad_payloads):
        response = client.post(
            f"/sessions/{session_id}/scene/operations",
            json={
                "operation_id": f"op-bad-{index}",
                "expected_scene_revision": 0,
                "action": action,
            },
            headers=headers,
        )
        assert response.status_code == 422, response.text
    nan_body = json.dumps(
        {
            "operation_id": "op-nan",
            "expected_scene_revision": 0,
            "action": {
                "op": "add_stroke",
                "points": [{"x": float("nan"), "y": 1}, {"x": 2, "y": 2}],
            },
        }
    )
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        content=nan_body,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert snapshot(client, headers, session_id)["objects"] == []


def test_erase_undo_and_redo_walk_through_own_history(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    first = commit(client, headers, session_id, "op-1", 0, stroke(10.0))
    second = commit(client, headers, session_id, "op-2", 1, stroke(300.0))
    scene = snapshot(client, headers, session_id)
    assert scene["student_undo_available"] is True
    assert scene["student_redo_available"] is False

    # Erase targets exactly the intended stroke.
    erased = commit(
        client, headers, session_id, "op-3", 2,
        {"op": "erase_object", "target_object_id": first["object_id"]},
    )
    assert erased["kind"] == "erase_object"
    assert visible_ids(snapshot(client, headers, session_id)) == [second["object_id"]]

    undone = commit(client, headers, session_id, "op-4", 3, {"op": "undo"})
    assert undone["affected_object_ids"] == [first["object_id"]]
    assert set(visible_ids(snapshot(client, headers, session_id))) == {
        first["object_id"],
        second["object_id"],
    }

    undone = commit(client, headers, session_id, "op-5", 4, {"op": "undo"})
    assert undone["affected_object_ids"] == [second["object_id"]]
    assert visible_ids(snapshot(client, headers, session_id)) == [first["object_id"]]

    redone = commit(client, headers, session_id, "op-6", 5, {"op": "redo"})
    assert redone["affected_object_ids"] == [second["object_id"]]
    redone = commit(client, headers, session_id, "op-7", 6, {"op": "redo"})
    assert redone["affected_object_ids"] == [first["object_id"]]
    assert visible_ids(snapshot(client, headers, session_id)) == [second["object_id"]]

    scene = snapshot(client, headers, session_id)
    assert scene["student_redo_available"] is False
    for name, op, expected in [
        ("op-r2", {"op": "redo"}, 7),
        ("op-u3", None, None),
    ]:
        if op is None:
            continue
        response = client.post(
            f"/sessions/{session_id}/scene/operations",
            json={"operation_id": name, "expected_scene_revision": expected, "action": op},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "nothing_to_redo"


def test_nothing_to_undo_on_an_empty_history(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={"operation_id": "op-u0", "expected_scene_revision": 0, "action": {"op": "undo"}},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "nothing_to_undo"
    assert snapshot(client, headers, session_id)["scene_revision"] == 0


def test_a_new_stroke_invalidates_the_redo_stack(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    commit(client, headers, session_id, "op-1", 0, stroke(10.0))
    commit(client, headers, session_id, "op-2", 1, {"op": "undo"})
    commit(client, headers, session_id, "op-3", 2, stroke(300.0))
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={"operation_id": "op-4", "expected_scene_revision": 3, "action": {"op": "redo"}},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "nothing_to_redo"


def test_student_cannot_erase_tutor_or_unknown_objects(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    check_in(client, headers, session_id)
    scene = snapshot(client, headers, session_id)
    (statement,) = scene["objects"]
    assert statement["author_role"] == "tutor"
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={
            "operation_id": "op-er-tutor",
            "expected_scene_revision": scene["scene_revision"],
            "action": {"op": "erase_object", "target_object_id": statement["id"]},
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_student_object"
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={
            "operation_id": "op-er-missing",
            "expected_scene_revision": scene["scene_revision"],
            "action": {"op": "erase_object", "target_object_id": "no-such-object"},
        },
        headers=headers,
    )
    assert response.status_code == 404
    assert snapshot(client, headers, session_id)["objects"] == [statement]


def test_tutor_move_undo_removes_the_group_and_preserves_student_history(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    check_in(client, headers, session_id)
    # Interleave: student stroke before the tutor move, the move, then a stroke after it.
    first_stroke = commit(
        client, headers, session_id, "op-s1",
        snapshot(client, headers, session_id)["scene_revision"], stroke(10.0),
    )
    turn = submit_partial_distribution(client, headers, session_id)
    tutor_object_ids = [d["object_id"] for d in turn["drawings"]]
    scene = snapshot(client, headers, session_id)
    assert set(visible_ids(scene)) >= {first_stroke["object_id"], *tutor_object_ids}
    assert scene["tutor_move_undo_available"] is True
    second_stroke = commit(
        client, headers, session_id, "op-s2", scene["scene_revision"], stroke(600.0)
    )

    undone = commit(
        client, headers, session_id, "op-tu",
        snapshot(client, headers, session_id)["scene_revision"],
        {"op": "undo_tutor_move"},
    )
    assert undone["kind"] == "undo_tutor_move"
    assert sorted(undone["affected_object_ids"]) == sorted(tutor_object_ids)

    scene = snapshot(client, headers, session_id)
    remaining = visible_ids(scene)
    assert first_stroke["object_id"] in remaining
    assert second_stroke["object_id"] in remaining
    assert not set(tutor_object_ids) & set(remaining)
    # The problem statement is not part of the teaching move; it stays on the board.
    assert any(obj["semantic_role"] == "problem_statement" for obj in scene["objects"])
    assert scene["tutor_move_undo_available"] is False

    # The student's own undo/redo history is untouched by the tutor-move undo.
    assert scene["student_undo_available"] is True
    student_undo = commit(
        client, headers, session_id, "op-su", scene["scene_revision"], {"op": "undo"}
    )
    assert student_undo["affected_object_ids"] == [second_stroke["object_id"]]
    student_redo = commit(
        client, headers, session_id, "op-sr",
        snapshot(client, headers, session_id)["scene_revision"], {"op": "redo"},
    )
    assert student_redo["affected_object_ids"] == [second_stroke["object_id"]]
    assert second_stroke["object_id"] in visible_ids(snapshot(client, headers, session_id))

    # The move is already undone; there is no further tutor move to undo.
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={
            "operation_id": "op-tu2",
            "expected_scene_revision": snapshot(client, headers, session_id)["scene_revision"],
            "action": {"op": "undo_tutor_move"},
        },
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_tutor_move"

    # The operation feed shows the grouped move and its undo in order.
    feed = operations(client, headers, session_id)
    tutor_ops = [
        op
        for op in feed["operations"]
        if op["move_id"] == turn["turn_id"] and op["author_role"] == "tutor"
    ]
    assert {op["kind"] for op in tutor_ops} == {"add_object"}
    undo_ops = [op for op in feed["operations"] if op["kind"] == "undo_tutor_move"]
    assert [op["move_id"] for op in undo_ops] == [turn["turn_id"]]
    seqs = [op["seq"] for op in feed["operations"]]
    assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1))


def test_erased_and_undone_objects_stay_hidden_after_a_restart(
    board: tuple[TestClient, dict[str, str], str], seeded_db_url: str, database: Database
) -> None:
    client, headers, session_id = board
    first = commit(client, headers, session_id, "op-1", 0, stroke(10.0))
    commit(client, headers, session_id, "op-2", 1, stroke(300.0))
    commit(
        client, headers, session_id, "op-3", 2,
        {"op": "erase_object", "target_object_id": first["object_id"]},
    )
    commit(client, headers, session_id, "op-4", 3, {"op": "undo"})
    commit(client, headers, session_id, "op-5", 4, {"op": "undo"})
    before = snapshot(client, headers, session_id)
    assert visible_ids(before) == [first["object_id"]]

    # Simulate a process restart: a brand-new Database over the same file.
    database.dispose()
    restarted = Database(seeded_db_url)
    try:
        with restarted.transaction() as db:
            rows = {
                row.id: row
                for row in db.execute(
                    select(SceneObjectRow).where(SceneObjectRow.session_id == session_id)
                ).scalars()
            }
        assert rows[first["object_id"]].deleted_at is None
        other = [row for row in rows.values() if row.id != first["object_id"]]
        assert other and all(row.deleted_at is not None for row in other)
    finally:
        restarted.dispose()

    after = snapshot(client, headers, session_id)
    assert visible_ids(after) == visible_ids(before)
    assert after["scene_revision"] == before["scene_revision"]


def test_operations_feed_supports_outbox_resync(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    commit(client, headers, session_id, "op-1", 0, stroke(10.0))
    second = commit(client, headers, session_id, "op-2", 1, stroke(300.0))
    commit(
        client, headers, session_id, "op-3", 2,
        {"op": "erase_object", "target_object_id": second["object_id"]},
    )
    feed = operations(client, headers, session_id)
    assert feed["scene_revision"] == 3
    assert [(op["seq"], op["kind"]) for op in feed["operations"]] == [
        (1, "add_object"),
        (2, "add_object"),
        (3, "erase_object"),
    ]
    # A reconnecting client asks only for what it has not seen.
    incremental = operations(client, headers, session_id, after_seq=2)
    assert [op["seq"] for op in incremental["operations"]] == [3]
    assert incremental["operations"][0]["object_id"] == second["object_id"]


def test_scene_operations_never_create_student_evidence(
    board: tuple[TestClient, dict[str, str], str], database: Database
) -> None:
    client, headers, session_id = board
    with database.transaction() as db:
        before = len(list(db.execute(select(ObservationRow.id)).scalars()))
    commit(client, headers, session_id, "op-1", 0, stroke())
    commit(client, headers, session_id, "op-2", 1, {"op": "undo"})
    commit(client, headers, session_id, "op-3", 2, {"op": "redo"})
    with database.transaction() as db:
        after = len(list(db.execute(select(ObservationRow.id)).scalars()))
    assert after == before  # scene edits are board state, never learning evidence
    scene = snapshot(client, headers, session_id)
    assert all(obj["author_role"] == "student" for obj in scene["objects"])


def test_tutor_objects_are_marked_as_tutor_and_never_student_work(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    check_in(client, headers, session_id)
    turn = submit_partial_distribution(client, headers, session_id)
    scene = snapshot(client, headers, session_id)
    by_id = {obj["id"]: obj for obj in scene["objects"]}
    for drawing in turn["drawings"]:
        obj = by_id[drawing["object_id"]]
        assert obj["author_role"] == "tutor"
        assert obj["teaching_step_id"] == turn["turn_id"]
        assert obj["payload"]["color_role"] == "tutor"
        assert obj["provenance"] == "submitted"


def test_ended_sessions_reject_new_operations_but_stay_readable(
    board: tuple[TestClient, dict[str, str], str]
) -> None:
    client, headers, session_id = board
    commit(client, headers, session_id, "op-1", 0, stroke())
    assert client.post(f"/sessions/{session_id}/end", headers=headers).status_code == 200
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={"operation_id": "op-2", "expected_scene_revision": 1, "action": stroke(99.0)},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_not_active"
    scene = snapshot(client, headers, session_id)
    assert len(scene["objects"]) == 1
    assert operations(client, headers, session_id)["operations"]


def test_another_learner_cannot_read_or_write_the_scene(
    client: TestClient,
) -> None:
    _, a = bootstrap(client, "Learner A")
    _, b = bootstrap(client, "Learner B")
    session_id = start_session(client, a)
    commit(client, a, session_id, "op-1", 0, stroke())
    for method, path in [
        ("GET", f"/sessions/{session_id}/scene"),
        ("GET", f"/sessions/{session_id}/scene/operations"),
    ]:
        response = client.request(method, path, headers=b)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={"operation_id": "op-x", "expected_scene_revision": 0, "action": stroke(5.0)},
        headers=b,
    )
    assert response.status_code == 404
    # A's scene is unchanged by B's attempts.
    assert len(snapshot(client, a, session_id)["objects"]) == 1
    assert snapshot(client, a, session_id)["scene_revision"] == 1
