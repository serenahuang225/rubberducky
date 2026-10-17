"""The durable scene operation log: commits, author-safe history, snapshot and replay.

Every visible board change is one row in ``scene_operations`` with a monotonic per-session
``seq`` claimed by a compare-and-swap on ``sessions.scene_revision``. Student commands
(stroke, erase, undo, redo, tutor-move undo) arrive with a client-chosen operation id and
an expected revision, so an offline outbox can retry safely: identical retries replay the
stored outcome, changed content under a reused id conflicts, and a stale revision asks the
client to resync from the snapshot or the replay feed first.

Histories are author-safe by construction: student undo/redo walk only the student's own
add/erase operations, while ``undo_tutor_move`` reverses one whole tutor teaching move
(every op sharing its turn id) without touching student objects or the student's history
position. The materialized ``scene_objects.deleted_at`` is updated in the same transaction,
so the durable log and the queryable scene never disagree, even across a restart.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from app.db.models import SceneObjectRow, SceneOperationRow, SessionRow
from app.db.repositories import NotInScopeError, ScopedRepository
from app.schemas.learner import SceneObject
from app.schemas.scene import (
    MAX_REPLAY_OPERATIONS,
    AddStroke,
    AuthorRole,
    EraseObject,
    OperationKind,
    SceneAction,
    SceneOperationRequest,
    SceneOperationResult,
    SceneOperationsPage,
    SceneOperationView,
    SceneSnapshot,
)
from app.whiteboard.geometry import PEN_WIDTH

_NAMESPACE = uuid.UUID("c3b7a2e1-9d54-4f68-b1a3-7e5c0d92f481")
_EDIT_KINDS = ("add_object", "erase_object")


class SceneCommandError(Exception):
    """A scene command rejected without effects; mapped to an HTTP error by the API layer."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def student_object_id(learner_id: str, operation_id: str) -> str:
    """Deterministic object id for a student stroke; identical retries reuse it."""
    return str(uuid.uuid5(_NAMESPACE, f"student-stroke|{learner_id}|{operation_id}"))


def tutor_move_op_id(turn_id: str, index: int) -> str:
    """Deterministic op id for one action of a tutor teaching move."""
    return str(uuid.uuid5(_NAMESPACE, f"tutor-move|{turn_id}|{index}"))


def statement_op_id(session_id: str, problem_id: str) -> str:
    """Deterministic op id for a posed problem statement (created at most once)."""
    return str(uuid.uuid5(_NAMESPACE, f"statement|{session_id}|{problem_id}"))


def _request_hash(action: SceneAction) -> str:
    payload = json.dumps(action.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _claim_seq(repo: ScopedRepository, session_id: str, expected: int | None) -> int:
    """Claim the next scene sequence number with an atomic compare-and-swap.

    ``expected=None`` is the unconditional server-side form used by tutor commits; student
    commands pass their expected revision so a concurrent commit is a conflict, not a lost
    update. The write acquired by the UPDATE serializes scene writers for this database.
    """
    query = (
        update(SessionRow)
        .where(SessionRow.id == session_id, SessionRow.learner_id == repo.learner_id)
        .values(scene_revision=SessionRow.scene_revision + 1)
    )
    if expected is not None:
        query = query.where(SessionRow.scene_revision == expected)
    result = repo.db.execute(query.execution_options(synchronize_session=False))
    if cast(CursorResult[object], result).rowcount != 1:
        current = repo.db.execute(
            select(SessionRow.scene_revision).where(
                SessionRow.id == session_id, SessionRow.learner_id == repo.learner_id
            )
        ).scalar_one()
        raise SceneCommandError(
            "revision_conflict",
            f"The scene is at revision {current}; resync before retrying this operation.",
        )
    return int(
        repo.db.execute(
            select(SessionRow.scene_revision).where(
                SessionRow.id == session_id, SessionRow.learner_id == repo.learner_id
            )
        ).scalar_one()
    )


def _append(
    repo: ScopedRepository,
    session_id: str,
    *,
    seq: int,
    operation_id: str,
    author_role: AuthorRole,
    kind: OperationKind,
    object_id: str | None,
    move_id: str | None,
    reverses_op_id: str | None,
    consumes_op_id: str | None,
    affected: list[str],
    request_hash: str,
    now: datetime,
) -> SceneOperationRow:
    row = SceneOperationRow(
        learner_id=repo.learner_id,
        id=operation_id,
        schema_version="scene-operation.v1",
        session_id=session_id,
        seq=seq,
        author_role=author_role,
        kind=kind,
        object_id=object_id,
        move_id=move_id,
        reverses_op_id=reverses_op_id,
        consumes_op_id=consumes_op_id,
        affected_object_ids=affected,
        request_hash=request_hash,
        reversed_by=None,
        created_at=now,
    )
    repo.db.add(row)
    repo.db.flush()
    return row


def _result(row: SceneOperationRow, *, replayed: bool) -> SceneOperationResult:
    return SceneOperationResult(
        operation_id=row.id,
        session_id=row.session_id,
        scene_revision=row.seq,
        kind=cast(OperationKind, row.kind),
        author_role=cast(AuthorRole, row.author_role),
        object_id=row.object_id,
        affected_object_ids=list(row.affected_object_ids),
        replayed=replayed,
        created_at=row.created_at,
    )


def _set_visible(repo: ScopedRepository, object_id: str, visible: bool, now: datetime) -> None:
    row = repo.db.get(SceneObjectRow, object_id)
    if row is None or row.learner_id != repo.learner_id:
        raise NotInScopeError("scene_objects")
    row.deleted_at = None if visible else now


def _apply(
    repo: ScopedRepository, target: SceneOperationRow, *, reverse: bool, now: datetime
) -> None:
    """Apply or reverse one add/erase op's effect on its object's materialized visibility."""
    if target.object_id is None:
        return
    # add_object shows its object when applied; erase_object hides it. Reversal flips that.
    _set_visible(repo, target.object_id, (target.kind == "add_object") != reverse, now)


def _own_ops(
    repo: ScopedRepository, session_id: str, author_role: AuthorRole
) -> list[SceneOperationRow]:
    return list(
        repo.db.execute(
            select(SceneOperationRow)
            .where(
                SceneOperationRow.learner_id == repo.learner_id,
                SceneOperationRow.session_id == session_id,
                SceneOperationRow.author_role == author_role,
            )
            .order_by(SceneOperationRow.seq)
        ).scalars()
    )


def _student_undo_target(repo: ScopedRepository, session_id: str) -> SceneOperationRow | None:
    """The student's latest own add/erase that is still in effect (LIFO history)."""
    return repo.db.execute(
        select(SceneOperationRow)
        .where(
            SceneOperationRow.learner_id == repo.learner_id,
            SceneOperationRow.session_id == session_id,
            SceneOperationRow.author_role == "student",
            SceneOperationRow.kind.in_(_EDIT_KINDS),
            SceneOperationRow.reversed_by.is_(None),
        )
        .order_by(SceneOperationRow.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _student_redo_target(
    repo: ScopedRepository, session_id: str
) -> tuple[SceneOperationRow, SceneOperationRow] | None:
    """The latest unconsumed student undo and the op it reversed, if redo is still valid.

    A new add/erase after an undo invalidates the redo stack, exactly like a text editor:
    the undone op stays reversed and is no longer offered as a redo candidate.
    """
    ops = _own_ops(repo, session_id, "student")
    consumed = {op.consumes_op_id for op in ops if op.kind == "redo"}
    undos = [op for op in ops if op.kind == "undo" and op.id not in consumed]
    if not undos:
        return None
    latest_undo = undos[-1]
    if any(op.kind in _EDIT_KINDS and op.seq > latest_undo.seq for op in ops):
        return None
    target = next((op for op in ops if op.reversed_by == latest_undo.id), None)
    return None if target is None else (latest_undo, target)


def _tutor_move_target(repo: ScopedRepository, session_id: str) -> str | None:
    """The latest tutor teaching move (move id) that has not been undone as a group."""
    tutor_ops = [
        op
        for op in _own_ops(repo, session_id, "tutor")
        if op.move_id is not None and op.kind in _EDIT_KINDS
    ]
    undone_moves = {
        op.move_id
        for op in _own_ops(repo, session_id, "student")
        if op.kind == "undo_tutor_move"
    }
    candidates = [op for op in tutor_ops if op.move_id not in undone_moves]
    if not candidates:
        return None
    return candidates[-1].move_id


def log_tutor_add(
    repo: ScopedRepository,
    session_id: str,
    turn_id: str,
    index: int,
    object_id: str,
    content: dict[str, object],
    now: datetime,
) -> None:
    """Log one tutor move object; the object row itself is written by the caller."""
    _append(
        repo,
        session_id,
        seq=_claim_seq(repo, session_id, None),
        operation_id=tutor_move_op_id(turn_id, index),
        author_role="tutor",
        kind="add_object",
        object_id=object_id,
        move_id=turn_id,
        reverses_op_id=None,
        consumes_op_id=None,
        affected=[object_id],
        request_hash=_content_hash(json.dumps(content, sort_keys=True, default=str)),
        now=now,
    )


def log_tutor_erase(
    repo: ScopedRepository,
    session_id: str,
    turn_id: str,
    index: int,
    object_id: str,
    now: datetime,
) -> None:
    """Log an erase inside a tutor move; the object row is updated by the caller."""
    _append(
        repo,
        session_id,
        seq=_claim_seq(repo, session_id, None),
        operation_id=tutor_move_op_id(turn_id, index),
        author_role="tutor",
        kind="erase_object",
        object_id=object_id,
        move_id=turn_id,
        reverses_op_id=None,
        consumes_op_id=None,
        affected=[object_id],
        request_hash=_content_hash(f"erase|{object_id}"),
        now=now,
    )


def log_statement_add(
    repo: ScopedRepository, session_id: str, problem_id: str, object_id: str, now: datetime
) -> None:
    """Log the posed statement as a tutor object outside any teaching-move group."""
    _append(
        repo,
        session_id,
        seq=_claim_seq(repo, session_id, None),
        operation_id=statement_op_id(session_id, problem_id),
        author_role="tutor",
        kind="add_object",
        object_id=object_id,
        move_id=None,
        reverses_op_id=None,
        consumes_op_id=None,
        affected=[object_id],
        request_hash=_content_hash(f"statement|{object_id}"),
        now=now,
    )


def commit_operation(
    repo: ScopedRepository,
    session_id: str,
    body: SceneOperationRequest,
    now: datetime,
) -> SceneOperationResult:
    """Validate and atomically commit one client scene operation (the caller commits).

    Order matters: the idempotency lookup runs before anything is written, then the CAS
    claims the next sequence (serializing scene writers), and only then is the action
    validated and applied. A failure raises, the caller rolls back, and the claimed
    sequence is released, so rejected commands leave neither effects nor revision gaps.
    """
    session = repo.require_session(session_id)
    existing = repo.db.execute(
        select(SceneOperationRow).where(
            SceneOperationRow.learner_id == repo.learner_id,
            SceneOperationRow.id == body.operation_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != _request_hash(body.action):
            raise SceneCommandError(
                "idempotency_conflict",
                "This operation id was already used with different content.",
            )
        return _result(existing, replayed=True)
    if session.status != "active":
        raise SceneCommandError("session_not_active", "The session is not active.")

    seq = _claim_seq(repo, session_id, body.expected_scene_revision)
    action = body.action
    request_hash = _request_hash(action)

    if isinstance(action, AddStroke):
        object_id = student_object_id(repo.learner_id, body.operation_id)
        repo.db.add(
            SceneObjectRow(
                id=object_id,
                schema_version="scene-object.v1",
                learner_id=repo.learner_id,
                session_id=session_id,
                author_role="student",
                semantic_role="work",
                kind="path",
                # The server assigns the fixed pen width and the locked student color role;
                # the client can propose neither.
                payload={
                    "points": [p.model_dump(mode="json") for p in action.points],
                    "width": PEN_WIDTH,
                    "color_role": "student",
                },
                teaching_step_id=None,
                provenance="submitted",
                created_at=now,
                deleted_at=None,
            )
        )
        row = _append(
            repo,
            session_id,
            seq=seq,
            operation_id=body.operation_id,
            author_role="student",
            kind="add_object",
            object_id=object_id,
            move_id=None,
            reverses_op_id=None,
            consumes_op_id=None,
            affected=[object_id],
            request_hash=request_hash,
            now=now,
        )
        return _result(row, replayed=False)

    if isinstance(action, EraseObject):
        erase_target = repo.db.execute(
            select(SceneObjectRow).where(
                SceneObjectRow.id == action.target_object_id,
                SceneObjectRow.learner_id == repo.learner_id,
                SceneObjectRow.session_id == session_id,
            )
        ).scalar_one_or_none()
        if erase_target is None:
            raise NotInScopeError("scene_objects")
        if erase_target.author_role != "student":
            raise SceneCommandError(
                "not_student_object", "Only your own marks can be erased this way."
            )
        if erase_target.deleted_at is not None:
            raise SceneCommandError("already_erased", "That mark is already erased.")
        erase_target.deleted_at = now
        row = _append(
            repo,
            session_id,
            seq=seq,
            operation_id=body.operation_id,
            author_role="student",
            kind="erase_object",
            object_id=erase_target.id,
            move_id=None,
            reverses_op_id=None,
            consumes_op_id=None,
            affected=[erase_target.id],
            request_hash=request_hash,
            now=now,
        )
        return _result(row, replayed=False)

    if action.op == "undo":
        undo_target = _student_undo_target(repo, session_id)
        if undo_target is None:
            raise SceneCommandError("nothing_to_undo", "There is nothing to undo.")
        _apply(repo, undo_target, reverse=True, now=now)
        undo_target.reversed_by = body.operation_id
        row = _append(
            repo,
            session_id,
            seq=seq,
            operation_id=body.operation_id,
            author_role="student",
            kind="undo",
            object_id=undo_target.object_id,
            move_id=None,
            reverses_op_id=undo_target.id,
            consumes_op_id=None,
            affected=[undo_target.object_id] if undo_target.object_id is not None else [],
            request_hash=request_hash,
            now=now,
        )
        return _result(row, replayed=False)

    if action.op == "redo":
        found = _student_redo_target(repo, session_id)
        if found is None:
            raise SceneCommandError("nothing_to_redo", "There is nothing to redo.")
        latest_undo, redo_target = found
        _apply(repo, redo_target, reverse=False, now=now)
        redo_target.reversed_by = None
        row = _append(
            repo,
            session_id,
            seq=seq,
            operation_id=body.operation_id,
            author_role="student",
            kind="redo",
            object_id=redo_target.object_id,
            move_id=None,
            reverses_op_id=redo_target.id,
            consumes_op_id=latest_undo.id,
            affected=[redo_target.object_id] if redo_target.object_id is not None else [],
            request_hash=request_hash,
            now=now,
        )
        return _result(row, replayed=False)

    # undo_tutor_move: reverse the latest tutor teaching move as one group.
    move_id = _tutor_move_target(repo, session_id)
    if move_id is None:
        raise SceneCommandError("no_tutor_move", "There is no tutor move to undo.")
    move_ops = [
        op
        for op in _own_ops(repo, session_id, "tutor")
        if op.move_id == move_id and op.kind in _EDIT_KINDS
    ]
    affected: list[str] = []
    for op in move_ops:
        _apply(repo, op, reverse=True, now=now)
        op.reversed_by = body.operation_id
        if op.object_id is not None:
            affected.append(op.object_id)
    row = _append(
        repo,
        session_id,
        seq=seq,
        operation_id=body.operation_id,
        author_role="student",
        kind="undo_tutor_move",
        object_id=None,
        move_id=move_id,
        reverses_op_id=None,
        consumes_op_id=None,
        affected=affected,
        request_hash=request_hash,
        now=now,
    )
    return _result(row, replayed=False)


def scene_snapshot(repo: ScopedRepository, session_id: str) -> SceneSnapshot:
    """The current visible objects and history availability; reads work for ended sessions."""
    session = repo.require_session(session_id)
    rows = list(
        repo.db.execute(
            select(SceneObjectRow)
            .where(
                SceneObjectRow.learner_id == repo.learner_id,
                SceneObjectRow.session_id == session_id,
                SceneObjectRow.deleted_at.is_(None),
            )
            .order_by(SceneObjectRow.created_at, SceneObjectRow.id)
        ).scalars()
    )
    return SceneSnapshot(
        session_id=session_id,
        scene_revision=session.scene_revision,
        objects=[SceneObject.model_validate(row) for row in rows],
        student_undo_available=_student_undo_target(repo, session_id) is not None,
        student_redo_available=_student_redo_target(repo, session_id) is not None,
        tutor_move_undo_available=_tutor_move_target(repo, session_id) is not None,
    )


def list_operations(
    repo: ScopedRepository, session_id: str, after_seq: int, limit: int
) -> SceneOperationsPage:
    """The replay feed: committed operations after ``after_seq``, in order, bounded."""
    session = repo.require_session(session_id)
    bounded = max(1, min(limit, MAX_REPLAY_OPERATIONS))
    rows = list(
        repo.db.execute(
            select(SceneOperationRow)
            .where(
                SceneOperationRow.learner_id == repo.learner_id,
                SceneOperationRow.session_id == session_id,
                SceneOperationRow.seq > after_seq,
            )
            .order_by(SceneOperationRow.seq)
            .limit(bounded)
        ).scalars()
    )
    return SceneOperationsPage(
        session_id=session_id,
        scene_revision=session.scene_revision,
        operations=[
            SceneOperationView(
                operation_id=row.id,
                seq=row.seq,
                author_role=cast(AuthorRole, row.author_role),
                kind=cast(OperationKind, row.kind),
                object_id=row.object_id,
                move_id=row.move_id,
                affected_object_ids=list(row.affected_object_ids),
                created_at=row.created_at,
            )
            for row in rows
        ],
    )
