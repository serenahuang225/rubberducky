"""Find blank board space for tutor equations without moving the learner's ink."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.db.models import SceneObjectRow

Bounds = tuple[float, float, float, float]


def bounds(kind: str, payload: Mapping[str, Any]) -> Bounds | None:
    points = payload.get("points")
    if isinstance(points, list) and points:
        xs, ys = [p["x"] for p in points], [p["y"] for p in points]
        return min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20
    text = payload.get("text")
    at = payload.get("at") or {"x": payload.get("x"), "y": payload.get("y")}
    if isinstance(text, str) and at.get("x") is not None and at.get("y") is not None:
        size = payload.get("font_size", 44 if kind == "add_math" else 32)
        wrapped: list[str] = [""]
        for word in text.split():
            candidate = (wrapped[-1] + " " + word).strip()
            if kind == "text" and len(candidate) > 48 and wrapped[-1]:
                wrapped.append(word)
            else:
                wrapped[-1] = candidate
        lines = len(wrapped) if kind == "text" else 1
        width = max(map(len, wrapped)) * size * 0.6 if kind == "text" else len(text) * size * 0.6
        return (
            at["x"] - 16,
            at["y"] - size - 16,
            at["x"] + width + 16,
            at["y"] + (lines - 1) * 40 + 20,
        )
    start, end = payload.get("start"), payload.get("end")
    if isinstance(start, dict) and isinstance(end, dict):
        return (
            min(start["x"], end["x"]) - 12,
            min(start["y"], end["y"]) - 12,
            max(start["x"], end["x"]) + 12,
            max(start["y"], end["y"]) + 12,
        )
    return None


def place_equation(
    payload: dict[str, Any],
    objects: Sequence[SceneObjectRow],
    occupied: list[Bounds],
) -> dict[str, Any] | None:
    size = min(44.0, 1160 / max(len(payload["text"]) * 0.6, 1))
    width, height = len(payload["text"]) * size * 0.6 + 32, size + 40
    obstacles = [
        box
        for obj in objects
        if obj.semantic_role != "teaching_note"
        and (box := bounds(obj.kind, obj.payload)) is not None
    ] + occupied
    requested = payload["at"]
    candidates = [(requested["x"] - 16, requested["y"] - size - 16)]
    next_row = max(80, int(requested["y"]) + 40)
    rows = [*range(next_row, 1100, 90), *range(80, min(next_row, 1100), 90)]
    candidates += [(float(x), float(y)) for y in rows for x in range(60, 1320, 60)]
    for x, y in candidates:
        box = (x, y, x + width, y + height)
        if x < 40 or y < 60 or box[2] > 1380 or box[3] > 1120:
            continue
        if any(x < b[2] and box[2] > b[0] and y < b[3] and box[3] > b[1] for b in obstacles):
            continue
        occupied.append(box)
        return {**payload, "at": {"x": x + 16, "y": y + size + 16}, "font_size": size}
    # A full board gets the explanation in chat, rather than overwriting student work.
    return None
