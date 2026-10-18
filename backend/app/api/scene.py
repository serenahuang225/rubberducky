"""Scene routes: commit one operation per edit, read the snapshot, replay the log.

All routes are learner-scoped through the paired bearer credential. Commits carry a
client-chosen operation id and the expected scene revision, so an offline outbox can retry
a finished stroke exactly once: identical retries replay the stored outcome, a reused id
with different content conflicts, and a stale revision is rejected for resync. History is
author-safe: student undo/redo never touch tutor objects, and ``undo_tutor_move`` reverses
one whole teaching move without disturbing the student's own history.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field

from app.api.deps import ScopedRepo, SettingsDep
from app.api.errors import ApiError, ErrorEnvelope
from app.api.sessions import SessionIdPath
from app.clock import utc_now
from app.schemas.common import ContractModel
from app.schemas.scene import (
    MAX_REPLAY_OPERATIONS,
    SceneOperationRequest,
    SceneOperationResult,
    SceneOperationsPage,
    SceneSnapshot,
)
from app.tutor.brought_question import BroughtQuestionError
from app.whiteboard.reading import has_answer_box, read_ink
from app.whiteboard.scene import (
    SceneCommandError,
    commit_operation,
    list_operations,
    scene_snapshot,
)

router = APIRouter(tags=["scene"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
}


@router.get(
    "/sessions/{session_id}/scene",
    response_model=SceneSnapshot,
    responses=_ERRORS,
    summary="Current visible board: objects, scene revision, board/pen spec, history flags",
)
def get_scene(session_id: SessionIdPath, repo: ScopedRepo) -> SceneSnapshot:
    return scene_snapshot(repo, session_id)


@router.get(
    "/sessions/{session_id}/scene/operations",
    response_model=SceneOperationsPage,
    responses=_ERRORS,
    summary="Replay feed: committed scene operations after a sequence number, in order",
)
def get_scene_operations(
    session_id: SessionIdPath,
    repo: ScopedRepo,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_REPLAY_OPERATIONS)] = MAX_REPLAY_OPERATIONS,
) -> SceneOperationsPage:
    return list_operations(repo, session_id, after_seq, limit)


@router.post(
    "/sessions/{session_id}/scene/operations",
    response_model=SceneOperationResult,
    responses=_ERRORS,
    summary="Commit one scene operation (stroke, erase, undo, redo, tutor-move undo)",
)
def post_scene_operation(
    session_id: SessionIdPath, body: SceneOperationRequest, repo: ScopedRepo
) -> SceneOperationResult:
    try:
        result = commit_operation(repo, session_id, body, utc_now())
    except SceneCommandError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    # NotInScopeError (a missing, foreign or cross-session erase target) is handled
    # globally as the same 404 not_found, so no existence oracle leaks.
    repo.db.commit()
    return result


class BoardReadRequest(ContractModel):
    scene_revision: Annotated[int, Field(ge=0)]
    check_answer: bool = False


class BoardReadResult(ContractModel):
    text: str
    legible: bool
    boxed_answer: bool = False
    scene_revision: int


@router.post("/sessions/{session_id}/scene/read", response_model=BoardReadResult)
def read_board(
    session_id: SessionIdPath,
    body: BoardReadRequest,
    repo: ScopedRepo,
    settings: SettingsDep,
) -> BoardReadResult:
    snapshot = scene_snapshot(repo, session_id)
    if snapshot.scene_revision != body.scene_revision:
        raise ApiError(409, "revision_conflict", "The board changed before it could be read.")
    if settings.tutor_provider != "claude" or not settings.external_integrations_enabled:
        raise ApiError(503, "tutor_not_configured", "Board reading needs the Claude tutor.")
    # Release the read transaction before the remote request.
    repo.db.rollback()
    boxed_answer = body.check_answer or has_answer_box(snapshot)
    try:
        if boxed_answer:
            text, legible = read_ink(settings, snapshot, verify=True)
        else:
            text, legible = read_ink(settings, snapshot)
    except BroughtQuestionError as error:
        raise ApiError(502, "board_read_failed", error.message) from error
    return BoardReadResult(
        text=text,
        legible=legible,
        boxed_answer=boxed_answer,
        scene_revision=snapshot.scene_revision,
    )
