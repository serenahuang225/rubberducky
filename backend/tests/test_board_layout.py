from app.db.models import SceneObjectRow
from app.whiteboard.layout import bounds, place_equation


def test_equations_avoid_student_ink_and_each_other() -> None:
    ink = SceneObjectRow(
        kind="path",
        semantic_role="work",
        payload={
            "points": [{"x": 60, "y": 180}, {"x": 500, "y": 260}],
        },
    )
    occupied = []
    payload = {"text": "x = 4", "at": {"x": 80, "y": 240}}
    first = place_equation(payload, [ink], occupied)
    assert first is not None and first["at"] != payload["at"]
    second = place_equation(payload, [ink], occupied)
    assert second is not None and second["at"] != first["at"]
    a, b = occupied
    assert not (a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1])
    assert bounds("add_math", first) is not None


def test_full_board_does_not_get_overwritten() -> None:
    ink = SceneObjectRow(
        kind="path",
        semantic_role="work",
        payload={
            "points": [{"x": 0, "y": 0}, {"x": 1600, "y": 1200}],
        },
    )
    assert place_equation({"text": "x = 4", "at": {"x": 80, "y": 240}}, [ink], []) is None
