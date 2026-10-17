"""Normalized provider events and the draft contract text sent to every language model.

Events describe what an adapter did (stream fragments, retries, the final decision). They
are operational telemetry: a ``delta`` is an unvalidated fragment of model text and must
never be shown to the learner as tutor speech. Only the validated draft returned by the
adapter can commit.
"""

import contextlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from app.inference.errors import MalformedDraftError, StaleDraftError
from app.inference.request import ProviderMessage
from app.pedagogy.policy import TurnPlan
from app.schemas.tutor import MAX_UTTERANCE_CHARS, TutorDraft

EventKind = Literal["started", "delta", "retry", "completed", "failed"]
EventSink = Callable[["ProviderEvent"], None]
MAX_RAW_OUTPUT_CHARS = 20_000
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


@dataclass(frozen=True)
class ProviderEvent:
    kind: EventKind
    sequence: int
    text: str = ""
    attempt: int = 1
    code: str | None = None
    detail: str | None = None


@dataclass
class EventRecorder:
    """Numbers events, keeps them, and forwards to an optional observer."""

    sink: EventSink | None = None
    events: list[ProviderEvent] = field(default_factory=list)

    def emit(self, kind: EventKind, **fields: object) -> None:
        event = ProviderEvent(kind=kind, sequence=len(self.events), **fields)  # type: ignore[arg-type]
        self.events.append(event)
        if self.sink is not None:
            # An observer must not be able to break a turn.
            with contextlib.suppress(Exception):
                self.sink(event)


@dataclass(frozen=True)
class AdapterCapabilities:
    streaming: bool
    cancellable: bool
    retries: bool
    # Where the learner context goes: "this_process", "loopback" or "remote_provider".
    transmission: Literal["this_process", "loopback", "remote_provider"]


@dataclass(frozen=True)
class DraftOutcome:
    draft: TutorDraft
    events: tuple[ProviderEvent, ...]
    attempts: int
    input_tokens: int | None = None
    output_tokens: int | None = None


def draft_contract_text(plan: TurnPlan, session_revision: int) -> str:
    """Appended to the system message: the exact object the model must return.

    Plan-controlled fields are given as fixed values so the model echoes them rather than
    inventing drawings, memory writes or disclosure; the coordinator still validates the
    result against the plan.
    """
    fixed = {
        "schema_version": "tutor-draft.v1",
        "turn_id": plan.turn_id,
        "session_revision": session_revision,
        "action_type": plan.action_type,
        "target_concept_ids": plan.target_concept_ids,
        "hint_level": plan.hint_level,
        "answer_revealed": plan.reveal_allowed,
        "drawing_actions": plan.drawing_actions,
        "expected_student_action": plan.expected_student_action,
        "proposed_memory_updates": [],
        "step_assessment": plan.step_status,
    }
    return (
        "\n\nRespond with ONE JSON object and nothing else (no prose, no code fence). "
        "Copy these fixed fields exactly: "
        f"{json.dumps(fixed, sort_keys=True, separators=(',', ':'))}. "
        f"Add 'utterance' (at most {MAX_UTTERANCE_CHARS} characters, the only words the "
        "learner sees), 'evidence_ids' and 'decision_justification' (at most 200 characters). "
        "'evidence_ids' must contain every ID in "
        f"{json.dumps(list(plan.required_evidence_ids), separators=(',', ':'))} "
        "and may add other IDs that appear in the context."
    )


def with_contract(
    messages: list[ProviderMessage], plan: TurnPlan, session_revision: int
) -> list[ProviderMessage]:
    """The request messages with the draft contract appended to the system message."""
    contract = draft_contract_text(plan, session_revision)
    out = list(messages)
    for index, message in enumerate(out):
        if message.role == "system":
            out[index] = message.model_copy(update={"content": message.content + contract})
            return out
    return [ProviderMessage(role="system", content=contract.strip()), *out]


def parse_final_draft(raw: str, *, turn_id: str, session_revision: int) -> TutorDraft:
    """Validate a *completed* model output; any doubt is a typed rejection, never a repair."""
    if len(raw) > MAX_RAW_OUTPUT_CHARS:
        raise MalformedDraftError("provider output exceeded the accepted size")
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        raise MalformedDraftError("provider output is not a JSON object")
    try:
        draft = TutorDraft.model_validate_json(text)
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "<root>" for e in error.errors()})
        raise MalformedDraftError("draft failed validation in: " + ", ".join(fields[:6])) from None
    if draft.turn_id != turn_id or draft.session_revision != session_revision:
        raise StaleDraftError(
            "draft addressed another turn or session revision than the current one"
        )
    return draft
