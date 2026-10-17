"""Validated tutor drawing tools and their durable scene effects.

A provider may only *propose* drawing actions. Each proposal must match one of six typed
tools with finite, bounded logical coordinates; unknown tools, extra fields (colors, HTML,
code), unsafe notation and over-budget payloads are rejected as a whole turn. The server
assigns tutor authorship and the locked tutor color role, so a draft cannot draw as the
student or pick an arbitrary color.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy import select

from app.db.models import SceneObjectRow
from app.db.repositories import ScopedRepository
from app.schemas.common import ContractModel, EntityId

# Geometry/bounds constants live in app.whiteboard.geometry and are re-exported here.
from app.whiteboard.geometry import (
    MAX_PATH_POINTS,
    MIN_SHAPE_EXTENT,
    Point,
)
from app.whiteboard.scene import log_tutor_add, log_tutor_erase

MAX_ACTIONS_PER_TURN = 6
MAX_TOTAL_POINTS = 400
MAX_PAYLOAD_BYTES = 12_000

_NAMESPACE = uuid.UUID("9d4f1f8e-2b6a-4c47-8c0e-5e3a71b2d9a4")

SemanticRole = Literal["problem_statement", "grouping_mark", "emphasis", "annotation", "focus"]
ShapeKind = Literal["circle", "rectangle", "line", "bracket", "arrow"]
# Digits, single-letter variables, + - * / = parentheses, spaces and a decimal point only.
SafeMathText = Annotated[
    str, Field(min_length=1, max_length=80, pattern=r"^[0-9a-z+\-*/=(). ]+$")
]
TermText = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[0-9a-z+\-*/=(). ]+$")]


class DrawPath(ContractModel):
    tool: Literal["draw_path"]
    semantic_role: SemanticRole
    points: Annotated[list[Point], Field(min_length=2, max_length=MAX_PATH_POINTS)]


class DrawShape(ContractModel):
    tool: Literal["draw_shape"]
    semantic_role: SemanticRole
    shape: ShapeKind
    start: Point
    end: Point


class AddMath(ContractModel):
    tool: Literal["add_math"]
    semantic_role: SemanticRole
    at: Point
    text: SafeMathText


class Highlight(ContractModel):
    tool: Literal["highlight"]
    semantic_role: SemanticRole
    target_object_id: EntityId
    term: TermText | None = None


class EraseTutorObject(ContractModel):
    tool: Literal["erase_tutor_object"]
    target_object_id: EntityId


class FocusRegion(ContractModel):
    tool: Literal["focus_region"]
    semantic_role: SemanticRole
    start: Point
    end: Point


ToolAction = Annotated[
    DrawPath | DrawShape | AddMath | Highlight | EraseTutorObject | FocusRegion,
    Field(discriminator="tool"),
]
_ADAPTER: TypeAdapter[ToolAction] = TypeAdapter(ToolAction)

ToolRejectionCode = Literal[
    "invalid_tool",
    "too_many_actions",
    "too_many_points",
    "payload_too_large",
    "degenerate_shape",
    "unknown_target",
    "not_tutor_object",
    "term_not_in_target",
]


class ToolRejection(ContractModel):
    index: Annotated[int, Field(ge=0)]
    code: ToolRejectionCode
    message: Annotated[str, Field(max_length=200)]


def _points(action: ToolAction) -> int:
    if isinstance(action, DrawPath):
        return len(action.points)
    if isinstance(action, DrawShape | FocusRegion):
        return 2
    return 1


def _degenerate(action: ToolAction) -> bool:
    if isinstance(action, DrawShape | FocusRegion):
        extent = max(abs(action.end.x - action.start.x), abs(action.end.y - action.start.y))
        return extent < MIN_SHAPE_EXTENT
    return False


def _target_text(row: SceneObjectRow) -> str:
    text = row.payload.get("text") if isinstance(row.payload, dict) else None
    return text if isinstance(text, str) else ""


def validate_tool_actions(
    repo: ScopedRepository, session_id: str, raw: Sequence[object]
) -> tuple[list[ToolAction], list[ToolRejection]]:
    """Validate a whole batch. Any rejection means no action from the batch may be applied."""
    rejections: list[ToolRejection] = []
    if len(raw) > MAX_ACTIONS_PER_TURN:
        return [], [
            ToolRejection(
                index=MAX_ACTIONS_PER_TURN,
                code="too_many_actions",
                message=f"at most {MAX_ACTIONS_PER_TURN} drawing actions per turn",
            )
        ]
    try:
        size = len(json.dumps(list(raw), default=str))
    except (TypeError, ValueError):
        size = MAX_PAYLOAD_BYTES + 1
    if size > MAX_PAYLOAD_BYTES:
        return [], [
            ToolRejection(index=0, code="payload_too_large", message="drawing payload too large")
        ]
    actions: list[ToolAction] = []
    total_points = 0
    for index, item in enumerate(raw):
        try:
            action = _ADAPTER.validate_python(item)
        except ValidationError as error:
            first = error.errors()[0]
            where = ".".join(str(part) for part in first["loc"]) or "action"
            rejections.append(
                ToolRejection(
                    index=index, code="invalid_tool", message=f"{where}: {first['msg']}"[:200]
                )
            )
            continue
        total_points += _points(action)
        if _degenerate(action):
            rejections.append(
                ToolRejection(index=index, code="degenerate_shape", message="shape has no extent")
            )
            continue
        if isinstance(action, Highlight | EraseTutorObject):
            row = repo.db.execute(
                select(SceneObjectRow).where(
                    SceneObjectRow.id == action.target_object_id,
                    SceneObjectRow.learner_id == repo.learner_id,
                    SceneObjectRow.session_id == session_id,
                    SceneObjectRow.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                rejections.append(
                    ToolRejection(index=index, code="unknown_target", message="no such object")
                )
                continue
            if isinstance(action, EraseTutorObject) and row.author_role != "tutor":
                rejections.append(
                    ToolRejection(
                        index=index,
                        code="not_tutor_object",
                        message="the tutor can only erase its own marks",
                    )
                )
                continue
            if (
                isinstance(action, Highlight)
                and action.term is not None
                and action.term not in _target_text(row)
            ):
                rejections.append(
                    ToolRejection(
                        index=index,
                        code="term_not_in_target",
                        message="highlighted term is not in the target object",
                    )
                )
                continue
        actions.append(action)
    if total_points > MAX_TOTAL_POINTS:
        rejections.append(
            ToolRejection(
                index=0, code="too_many_points", message=f"at most {MAX_TOTAL_POINTS} points"
            )
        )
    return (actions, []) if not rejections else ([], rejections)


def tutor_object_id(turn_id: str, index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{turn_id}|{index}"))


class AppliedDrawing(ContractModel):
    object_id: EntityId
    tool: Annotated[str, Field(max_length=40)]
    semantic_role: Annotated[str, Field(max_length=40)]


def _payload(action: ToolAction) -> dict[str, Any]:
    payload = action.model_dump(mode="json")
    payload["color_role"] = "tutor"
    return payload


def apply_tool_actions(
    repo: ScopedRepository,
    session_id: str,
    turn_id: str,
    actions: Sequence[ToolAction],
    now: datetime,
) -> list[AppliedDrawing]:
    """Write already-validated actions in the caller's transaction (no commit).

    Every action also lands in the durable scene operation log under the turn's move id,
    so a later tutor-move undo reverses the whole move as one group and the replay feed
    can rebuild the board in order.
    """
    applied: list[AppliedDrawing] = []
    for index, action in enumerate(actions):
        if isinstance(action, EraseTutorObject):
            row = repo.db.get(SceneObjectRow, action.target_object_id)
            if row is not None and row.author_role == "tutor" and row.deleted_at is None:
                row.deleted_at = now
            log_tutor_erase(repo, session_id, turn_id, index, action.target_object_id, now)
            applied.append(
                AppliedDrawing(
                    object_id=action.target_object_id, tool=action.tool, semantic_role="erased"
                )
            )
            continue
        object_id = tutor_object_id(turn_id, index)
        kind = action.shape if isinstance(action, DrawShape) else action.tool
        payload = _payload(action)
        repo.db.add(
            SceneObjectRow(
                id=object_id,
                schema_version="scene-object.v1",
                learner_id=repo.learner_id,
                session_id=session_id,
                author_role="tutor",
                semantic_role=action.semantic_role,
                kind=kind,
                payload=payload,
                teaching_step_id=turn_id,
                provenance="submitted",
                created_at=now,
                deleted_at=None,
            )
        )
        log_tutor_add(repo, session_id, turn_id, index, object_id, payload, now)
        applied.append(
            AppliedDrawing(
                object_id=object_id, tool=action.tool, semantic_role=action.semantic_role
            )
        )
    repo.db.flush()
    return applied


def text_of_actions(actions: Sequence[ToolAction]) -> list[str]:
    """Visible text a batch would put on the board (checked for answer disclosure)."""
    return [a.text for a in actions if isinstance(a, AddMath)] + [
        a.term for a in actions if isinstance(a, Highlight) and a.term is not None
    ]
