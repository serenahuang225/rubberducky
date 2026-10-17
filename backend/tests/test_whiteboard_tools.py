"""Validation and durable effects of the six typed tutor drawing tools."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utc_now
from app.db.database import Database
from app.db.models import SceneObjectRow
from app.pedagogy.problems import problem_spec
from app.tutor.evidence import ensure_statement_object
from app.whiteboard.tools import (
    MAX_ACTIONS_PER_TURN,
    MAX_PATH_POINTS,
    AddMath,
    apply_tool_actions,
    tutor_object_id,
    validate_tool_actions,
)
from tests.memory_fixtures import add_learner, add_session, scoped

NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
FIXTURE = problem_spec("problem.distribute_2x3_eq_14")


@pytest.fixture
def scene(database: Database) -> dict[str, str]:
    """A learner, an active session and the tutor-authored statement object on the board."""
    with database.transaction() as db:
        add_learner(db, "learner-wb", NOW)
        add_session(db, "learner-wb", "session-wb", NOW, status="active")
        repo = scoped(db, "learner-wb")
        statement_id = ensure_statement_object(repo, "session-wb", FIXTURE, utc_now())
    return {"learner_id": "learner-wb", "session_id": "session-wb", "statement_id": statement_id}


def _validate(db: DbSession, scene: dict[str, str], actions: list[object]):
    return validate_tool_actions(scoped(db, scene["learner_id"]), scene["session_id"], actions)


def test_valid_batch_applies_with_tutor_authorship_and_deterministic_ids(
    database: Database, scene: dict[str, str]
) -> None:
    batch = [
        {"tool": "highlight", "semantic_role": "emphasis",
         "target_object_id": scene["statement_id"], "term": "(x + 3)"},
        {"tool": "draw_shape", "semantic_role": "grouping_mark", "shape": "bracket",
         "start": {"x": 106.0, "y": 138.0}, "end": {"x": 288.0, "y": 138.0}},
    ]
    with database.transaction() as db:
        actions, rejections = _validate(db, scene, batch)
        assert rejections == []
        applied = apply_tool_actions(
            scoped(db, scene["learner_id"]), scene["session_id"], "turn-1", actions, utc_now()
        )
    assert [a.object_id for a in applied] == [
        tutor_object_id("turn-1", 0),
        tutor_object_id("turn-1", 1),
    ]
    with database.transaction() as db:
        rows = list(db.execute(select(SceneObjectRow)).scalars())
    created = {row.id: row for row in rows if row.teaching_step_id == "turn-1"}
    assert len(created) == 2
    for row in created.values():
        assert row.author_role == "tutor"
        assert row.payload["color_role"] == "tutor"
        assert row.provenance == "submitted"


@pytest.mark.parametrize(
    ("batch", "code"),
    [
        ([{"tool": "execute_js", "code": "alert(1)"}], "invalid_tool"),
        # Extra fields (here: a free color choice) are rejected, never ignored.
        ([{"tool": "draw_shape", "semantic_role": "annotation", "shape": "line",
           "start": {"x": 1, "y": 1}, "end": {"x": 50, "y": 50}, "color": "red"}], "invalid_tool"),
        ([{"tool": "add_math", "semantic_role": "annotation", "at": {"x": 10, "y": 10},
           "text": "x = 4; DROP TABLE steps"}], "invalid_tool"),
        ([{"tool": "draw_shape", "semantic_role": "annotation", "shape": "circle",
           "start": {"x": 10, "y": 10}, "end": {"x": 10.5, "y": 10.5}}], "degenerate_shape"),
        ([{"tool": "highlight", "semantic_role": "emphasis",
           "target_object_id": "no-such-object"}], "unknown_target"),
        ([{"tool": "draw_path", "semantic_role": "annotation",
           "points": [{"x": 10, "y": 10}, {"x": 2000, "y": 10}]}], "invalid_tool"),
    ],
)
def test_unsafe_or_malformed_actions_are_rejected_as_a_whole_batch(
    database: Database, scene: dict[str, str], batch: list[object], code: str
) -> None:
    # A valid action in front of the bad one must not be applied either.
    valid = {"tool": "focus_region", "semantic_role": "focus",
             "start": {"x": 0, "y": 0}, "end": {"x": 100, "y": 100}}
    with database.transaction() as db:
        before = len(list(db.execute(select(SceneObjectRow)).scalars()))
        actions, rejections = _validate(db, scene, [valid, *batch])
        assert actions == []
        assert [r.code for r in rejections] == [code]
        assert rejections[0].index == 1
        assert len(list(db.execute(select(SceneObjectRow)).scalars())) == before


def test_batch_size_and_point_budgets(database: Database, scene: dict[str, str]) -> None:
    dot = {"tool": "focus_region", "semantic_role": "focus",
           "start": {"x": 0, "y": 0}, "end": {"x": 100, "y": 100}}
    with database.transaction() as db:
        _, rejections = _validate(db, scene, [dot] * (MAX_ACTIONS_PER_TURN + 1))
        assert [r.code for r in rejections] == ["too_many_actions"]
        long_path = {
            "tool": "draw_path", "semantic_role": "annotation",
            "points": [
                {"x": float(i % 100), "y": float(i % 100)} for i in range(MAX_PATH_POINTS + 1)
            ],
        }
        _, rejections = _validate(db, scene, [long_path])
        assert [r.code for r in rejections] == ["invalid_tool"]
        # 450 points stays under the byte budget but exceeds the total point budget.
        two_long = [
            {"tool": "draw_path", "semantic_role": "annotation",
             "points": [{"x": float(i), "y": float(i)} for i in range(150)]}
            for _ in range(3)
        ]
        _, rejections = _validate(db, scene, two_long)
        assert [r.code for r in rejections] == ["too_many_points"]


def test_tutor_cannot_erase_student_marks(database: Database, scene: dict[str, str]) -> None:
    with database.transaction() as db:
        db.add(
            SceneObjectRow(
                id="student-stroke",
                schema_version="scene-object.v1",
                learner_id=scene["learner_id"],
                session_id=scene["session_id"],
                author_role="student",
                semantic_role="work",
                kind="path",
                payload={"points": [{"x": 1, "y": 1}, {"x": 5, "y": 5}]},
                teaching_step_id=None,
                provenance="submitted",
                created_at=utc_now(),
                deleted_at=None,
            )
        )
    with database.transaction() as db:
        _, rejections = _validate(
            db, scene, [{"tool": "erase_tutor_object", "target_object_id": "student-stroke"}]
        )
        assert [r.code for r in rejections] == ["not_tutor_object"]
    with database.transaction() as db:
        row = db.get(SceneObjectRow, "student-stroke")
        assert row is not None and row.deleted_at is None


def test_highlight_term_must_appear_in_the_target(
    database: Database, scene: dict[str, str]
) -> None:
    with database.transaction() as db:
        _, rejections = _validate(
            db,
            scene,
            [{"tool": "highlight", "semantic_role": "emphasis",
              "target_object_id": scene["statement_id"], "term": "(x + 9)"}],
        )
        assert [r.code for r in rejections] == ["term_not_in_target"]


def test_foreign_or_deleted_targets_are_indistinguishable_from_missing(
    database: Database, scene: dict[str, str]
) -> None:
    with database.transaction() as db:
        add_learner(db, "learner-other", NOW)
        add_session(db, "learner-other", "session-other", NOW, status="active")
        other_id = ensure_statement_object(
            scoped(db, "learner-other"), "session-other", FIXTURE, utc_now()
        )
        _, rejections = _validate(
            db, scene, [{"tool": "highlight", "semantic_role": "emphasis",
                         "target_object_id": other_id, "term": "(x + 3)"}]
        )
        assert [r.code for r in rejections] == ["unknown_target"]


def test_add_math_text_is_bounded_and_ascii_math() -> None:
    with pytest.raises(ValidationError):
        AddMath(
            tool="add_math",
            semantic_role="annotation",
            at={"x": 1, "y": 1},
            text="2(x + 3) = 14 <script>",
        )
