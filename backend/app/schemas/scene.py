"""Contracts for the durable scene: committed operations, snapshots and the replay feed.

A client commits exactly one operation per finished stroke or history action. The client
chooses the operation id (a UUID from its offline outbox), which makes retries safe: an
identical retry replays the stored outcome, and the same id with different content is a
conflict. ``expected_scene_revision`` is the optimistic-concurrency token for the session's
monotonic scene counter; a stale expectation is rejected so the client can resync from the
snapshot/replay endpoints and retry the same operation id.
"""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import ContractModel, EntityId, UtcDatetime
from app.schemas.learner import SceneObject
from app.whiteboard.geometry import BOARD_HEIGHT, BOARD_WIDTH, MAX_PATH_POINTS, PEN_WIDTH, Point

AuthorRole = Literal["student", "tutor"]
OperationKind = Literal["add_object", "erase_object", "undo", "redo", "undo_tutor_move"]

MAX_REPLAY_OPERATIONS = 500


class _Request(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AddStroke(_Request):
    """One finished student pen stroke. Dots (a single point) are valid strokes."""

    op: Literal["add_stroke"]
    points: Annotated[list[Point], Field(min_length=1, max_length=MAX_PATH_POINTS)]


class EraseObject(_Request):
    """Erase one of the student's own visible objects. Tutor objects are refused."""

    op: Literal["erase_object"]
    target_object_id: EntityId


class Undo(_Request):
    """Reverse the student's own latest stroke or erase that is still in effect."""

    op: Literal["undo"]


class Redo(_Request):
    """Reapply the student's own most recently undone operation."""

    op: Literal["redo"]


class UndoTutorMove(_Request):
    """Undo the tutor's latest teaching move (all of its objects) as one group.

    Student objects and the student's own undo/redo history are never affected.
    """

    op: Literal["undo_tutor_move"]


SceneAction = Annotated[
    AddStroke | EraseObject | Undo | Redo | UndoTutorMove,
    Field(discriminator="op"),
]


class SceneOperationRequest(_Request):
    schema_version: Literal["scene-operation-request.v1"] = "scene-operation-request.v1"
    operation_id: EntityId
    expected_scene_revision: Annotated[int, Field(ge=0)]
    action: SceneAction


class SceneOperationResult(ContractModel):
    """The authoritative outcome of one committed (or replayed) scene operation."""

    schema_version: Literal["scene-operation-result.v1"] = "scene-operation-result.v1"
    operation_id: EntityId
    session_id: EntityId
    # The session's scene revision after this operation; also the operation's seq.
    scene_revision: Annotated[int, Field(ge=0)]
    kind: OperationKind
    author_role: AuthorRole
    object_id: EntityId | None = None
    affected_object_ids: list[EntityId] = Field(default_factory=list)
    replayed: bool = False
    created_at: UtcDatetime


class SceneOperationView(ContractModel):
    """One entry of the replay feed a reconnecting client uses to catch up."""

    operation_id: EntityId
    seq: Annotated[int, Field(ge=1)]
    author_role: AuthorRole
    kind: OperationKind
    object_id: EntityId | None = None
    move_id: EntityId | None = None
    affected_object_ids: list[EntityId] = Field(default_factory=list)
    created_at: UtcDatetime


class SceneOperationsPage(ContractModel):
    schema_version: Literal["scene-operations.v1"] = "scene-operations.v1"
    session_id: EntityId
    scene_revision: Annotated[int, Field(ge=0)]
    operations: list[SceneOperationView]


class SceneSnapshot(ContractModel):
    """The current visible scene plus everything the history controls need to render."""

    schema_version: Literal["scene-snapshot.v1"] = "scene-snapshot.v1"
    session_id: EntityId
    scene_revision: Annotated[int, Field(ge=0)]
    board_width: float = BOARD_WIDTH
    board_height: float = BOARD_HEIGHT
    # The single fixed student pen width; there is no brush-size or free-color setting.
    pen_width: float = PEN_WIDTH
    objects: list[SceneObject]
    student_undo_available: bool
    student_redo_available: bool
    tutor_move_undo_available: bool
