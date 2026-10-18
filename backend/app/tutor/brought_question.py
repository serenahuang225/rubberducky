"""Tutor a question the learner brought, and show Claude's reply on the board.

The built-in algebra unit stays on its deterministic specs. A typed question, a text file,
or one screenshot is read by Claude. The words Claude returns are what the learner sees:
the prompt and a tutor note on the whiteboard. The image is sent for that call and is not
stored.
"""

import base64
import binascii
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.db.models import AttemptRow, ProblemRow, SceneObjectRow
from app.db.repositories import ScopedRepository
from app.inference.errors import ProviderError
from app.learner.pairing import new_id
from app.pedagogy.handhold import (
    clip_trace,
    explained_failure_flag,
    followup_system,
    opening_system,
)
from app.pedagogy.problems import (
    LINEAR_EQUATIONS,
    ProblemSpec,
    UnknownProblemError,
    problem_spec,
)
from app.schemas.curriculum import Problem
from app.schemas.learner import Personality
from app.schemas.tutor import MAX_UTTERANCE_CHARS, CheckInRequest, HandholdMode, LearnerControl
from app.whiteboard.scene import log_tutor_add, retire_tutor_objects
from app.whiteboard.tools import AddMath

LEARNER_PROBLEM_PREFIX = "problem.lrn."
MAX_QUESTION_IMAGE_BYTES = 1_500_000
TEACHING_X = 80.0
TEACHING_Y = 240.0
TEACHING_LINE_CHARS = 68
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)
_NOTE_NAMESPACE = uuid.UUID("c3a91e04-7b2d-4f58-9a16-0e5d8c2b7f41")

# Balanced is the default amount of help when a caller has not chosen a mode.
DISPLAY_SYSTEM = opening_system("balanced", "janelle")
FOLLOWUP_SYSTEM = followup_system("balanced", "none", "janelle")


class BroughtQuestionError(Exception):
    """A learner-safe failure while asking Claude to write the note that will be shown."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class BroughtQuestion:
    statement: str
    teaching: str
    next_step: str
    approach: str = ""
    contradiction: str = ""
    explained_failure: bool = False
    drawing_actions: tuple[dict[str, object], ...] = ()


def is_learner_problem(problem_id: str) -> bool:
    return problem_id.startswith(LEARNER_PROBLEM_PREFIX)


def has_brought_question(body: CheckInRequest) -> bool:
    text = (body.question_text or "").strip()
    return bool(text) or body.question_image_base64 is not None


def spec_for_stored_problem(repo: ScopedRepository, problem_id: str) -> ProblemSpec:
    """A curriculum spec, or the statement stored for a question the learner brought."""
    if not is_learner_problem(problem_id):
        return problem_spec(problem_id)
    row = repo.db.get(ProblemRow, problem_id)
    if row is None:
        raise UnknownProblemError(problem_id)
    return learner_spec(row.id, row.statement)


def learner_spec(problem_id: str, statement: str) -> ProblemSpec:
    return ProblemSpec(
        problem_id=problem_id,
        statement=statement,
        kind="practice",
        concept_id=LINEAR_EQUATIONS,
        step_concept_id=LINEAR_EQUATIONS,
    )


def parse_tutor_display(raw: str) -> BroughtQuestion:
    """The statement, the note to display, and the next instruction."""
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise BroughtQuestionError(
            "Claude's reply could not be shown. Try sending the question again."
        ) from error
    if not isinstance(data, dict):
        raise BroughtQuestionError(
            "Claude's reply could not be shown. Try sending the question again."
        )
    statement = _clip(data.get("statement"), 160)
    teaching = _clip(data.get("teaching"), MAX_UTTERANCE_CHARS)
    next_step = _clip(data.get("next_step"), 140) or "Show your next step on the board."
    if statement is None or teaching is None:
        raise BroughtQuestionError(
            "Claude's reply could not be shown. Try sending the question again."
        )
    equations = data.get("equations", [])
    if not isinstance(equations, list) or len(equations) > 2:
        raise BroughtQuestionError("The tutor sent too much board work. Try again.")
    drawing_actions: list[dict[str, object]] = []
    try:
        for index, equation in enumerate(equations):
            if not isinstance(equation, dict):
                raise ValueError("equation must be an object")
            action = AddMath.model_validate(
                {
                    "tool": "add_math",
                    "semantic_role": "annotation",
                    "at": {"x": TEACHING_X, "y": TEACHING_Y + index * 110},
                    "text": equation.get("text"),
                    "highlight_term": equation.get("highlight_term"),
                }
            )
            drawing_actions.append(action.model_dump(mode="json", exclude_none=True))
    except (ValueError, ValidationError) as error:
        raise BroughtQuestionError("The tutor's equation could not be shown. Try again.") from error
    return BroughtQuestion(
        drawing_actions=tuple(drawing_actions),
        statement=statement,
        teaching=teaching,
        next_step=next_step,
        approach=clip_trace(data.get("approach")),
        contradiction=clip_trace(data.get("contradiction")),
        explained_failure=explained_failure_flag(data.get("explained_failure")),
    )


def read_brought_question(
    settings: Settings, body: CheckInRequest, *, personality: Personality = "janelle"
) -> BroughtQuestion:
    """Ask Claude to read the question and write the note the learner will see."""
    blocks: list[dict[str, object]] = []
    if body.question_image_base64 is not None and body.question_image_media_type is not None:
        _validated_image(body.question_image_base64)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": body.question_image_media_type,
                    "data": body.question_image_base64,
                },
            }
        )
    typed = (body.question_text or "").strip()
    if typed:
        blocks.append({"type": "text", "text": typed})
    elif blocks:
        blocks.append(
            {
                "type": "text",
                "text": "The learner shared a picture of the question they are working on.",
            }
        )
    else:
        raise BroughtQuestionError("Type a question or attach a picture of it.")
    raw = complete_tutoring(
        settings, system=opening_system(body.handhold, personality), blocks=blocks
    )
    return parse_tutor_display(raw)


def follow_up_display(
    settings: Settings,
    *,
    statement: str,
    learner_text: str,
    prior_note: str | None,
    handhold: HandholdMode = "balanced",
    control: LearnerControl = "none",
    personality: Personality = "janelle",
    board_context: str | None = None,
    board_images: list[bytes] | None = None,
) -> BroughtQuestion:
    """Claude's next note, after the learner writes or asks for help."""
    parts = [f"Question: {statement}", f"Handhold: {handhold}."]
    if prior_note:
        parts.append(f"What you last showed them:\n{prior_note}")
    parts.append(f"What they just did:\n{learner_text or 'They asked for help.'}")
    if board_context:
        parts.append(board_context)
    blocks: list[dict[str, object]] = []
    for image in board_images or []:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(image).decode("ascii"),
                },
            }
        )
    blocks.append({"type": "text", "text": "\n\n".join(parts)})
    raw = complete_tutoring(
        settings,
        system=followup_system(handhold, control, personality),
        blocks=blocks,
    )
    parsed = parse_tutor_display(raw)
    # Keep the question they already see, even if the model restates it differently.
    return BroughtQuestion(
        statement=statement,
        teaching=parsed.teaching,
        drawing_actions=parsed.drawing_actions,
        next_step=parsed.next_step,
        approach=parsed.approach,
        contradiction=parsed.contradiction,
        explained_failure=parsed.explained_failure,
    )


def complete_tutoring(settings: Settings, *, system: str, blocks: list[dict[str, object]]) -> str:
    """One Claude call. Imported lazily so application startup does not load the SDK."""
    try:
        from app.inference.claude import ClaudeAdapter

        adapter = ClaudeAdapter.from_settings(settings)
        return adapter.complete_blocks(
            system=system,
            content=blocks,
            max_tokens=1_400,
            timeout=settings.tutor_remote_timeout_seconds,
        )
    except ProviderError as error:
        raise BroughtQuestionError(error.public_message) from error


def open_learner_problem(
    repo: ScopedRepository, session_id: str, question: BroughtQuestion, now: datetime
) -> tuple[ProblemSpec, AttemptRow, str]:
    """Store the question and pose its statement. Returns the spec, attempt and board id."""
    from app.tutor.evidence import ensure_attempt, ensure_statement_object

    problem_id = LEARNER_PROBLEM_PREFIX + new_id()
    record = Problem(
        id=problem_id,
        concept_id=LINEAR_EQUATIONS,
        statement=question.statement,
        kind="practice",
        created_at=now,
    )
    repo.db.add(ProblemRow(**record.model_dump()))
    repo.db.flush()
    spec = learner_spec(problem_id, question.statement)
    attempt = ensure_attempt(repo, session_id, problem_id, now)
    statement_id = ensure_statement_object(repo, session_id, spec, now)
    return spec, attempt, statement_id


def place_teaching_note(
    repo: ScopedRepository,
    session_id: str,
    turn_id: str,
    teaching: str,
    now: datetime,
    *,
    action_index: int = 0,
) -> str:
    """Replace the previous tutor note with the words Claude just wrote, and log the add."""
    previous = list(
        repo.db.execute(
            select(SceneObjectRow.id).where(
                SceneObjectRow.learner_id == repo.learner_id,
                SceneObjectRow.session_id == session_id,
                SceneObjectRow.semantic_role == "teaching_note",
                SceneObjectRow.deleted_at.is_(None),
            )
        ).scalars()
    )
    if previous:
        retire_tutor_objects(repo, session_id, previous, now)
    object_id = str(uuid.uuid5(_NOTE_NAMESPACE, f"teaching|{turn_id}"))
    payload: dict[str, object] = {
        "text": teaching,
        "lines": wrap_teaching(teaching),
        "x": TEACHING_X,
        "y": TEACHING_Y,
        "color_role": "tutor",
    }
    repo.db.add(
        SceneObjectRow(
            id=object_id,
            schema_version="scene-object.v1",
            learner_id=repo.learner_id,
            session_id=session_id,
            author_role="tutor",
            semantic_role="teaching_note",
            kind="text",
            payload=payload,
            teaching_step_id=turn_id,
            provenance="submitted",
            created_at=now,
            deleted_at=None,
        )
    )
    log_tutor_add(repo, session_id, turn_id, action_index, object_id, payload, now)
    repo.db.flush()
    return object_id


def wrap_teaching(text: str, width: int = TEACHING_LINE_CHARS) -> list[str]:
    """Greedy wrap so the board can show the note as readable lines."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        piece = word if not current else f"{current} {word}"
        if len(piece) > width and current:
            lines.append(current)
            current = word
        else:
            current = piece
    if current:
        lines.append(current)
    return lines[:22] or [text[:width]]


def _clip(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:limit]


def _validated_image(encoded: str) -> None:
    try:
        size = len(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError) as error:
        raise BroughtQuestionError("That picture could not be read. Try another one.") from error
    if size > MAX_QUESTION_IMAGE_BYTES:
        raise BroughtQuestionError("That picture is too large. Try a smaller screenshot.")
    if size == 0:
        raise BroughtQuestionError("That picture could not be read. Try another one.")
