"""Tutor provider adapters: a labeled protocol and the deterministic mock.

A provider receives the deterministic plan, the measured provider request and the bounded
context, and returns a :class:`TutorDraft`. It only proposes; the coordinator validates the
draft against the plan, the verifier and the context before anything is committed. The mock
is visibly labeled (``is_mock=True``) and renders wording straight from the plan, so the
whole production path (coordinator, retrieval, validation, persistence) is exercised in
development and tests without a language model.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from app.config import Settings
from app.inference.cancel import CancelToken
from app.inference.errors import ProviderUnavailableError
from app.inference.events import EventSink
from app.inference.request import ProviderRequest
from app.pedagogy.messages import render_utterance
from app.pedagogy.policy import TurnPlan
from app.schemas.context import TutorContext
from app.schemas.memory import CreateEpisodicNoteProposal, CreateSessionContextProposal
from app.schemas.tutor import ProviderLabel, TutorDraft

MOCK_LABEL = ProviderLabel(
    name="mock", is_mock=True, label="Deterministic mock tutor (not a language model)"
)
SESSION_TIREDNESS_TTL = timedelta(hours=2)
NOTE_REVIEW_DELAY = timedelta(days=14)
NOTE_LIFETIME = timedelta(days=90)


@dataclass(frozen=True)
class DraftInputs:
    """Everything a provider may use for one turn. Nothing here is writable state."""

    plan: TurnPlan
    request: ProviderRequest
    context: TutorContext
    learner_id: str
    session_id: str
    session_revision: int
    learner_text: str
    now: datetime
    # Cooperative cancel for the call and an optional observer of untrusted stream fragments.
    cancel: CancelToken = field(default_factory=CancelToken)
    on_event: EventSink | None = None


class TutorProvider(Protocol):
    """One bounded draft per turn. Implementations must not persist anything themselves."""

    def label(self) -> ProviderLabel: ...

    def draft(self, inputs: DraftInputs) -> TutorDraft: ...


class MockTutorProvider:
    """Deterministic wording from the plan, with only plan-sanctioned proposals."""

    def label(self) -> ProviderLabel:
        return MOCK_LABEL

    def draft(self, inputs: DraftInputs) -> TutorDraft:
        plan = inputs.plan
        return TutorDraft(
            turn_id=plan.turn_id,
            session_revision=inputs.session_revision,
            action_type=plan.action_type,
            utterance=render_utterance(plan),
            target_concept_ids=list(plan.target_concept_ids),
            evidence_ids=list(dict.fromkeys(plan.required_evidence_ids)),
            hint_level=plan.hint_level,
            answer_revealed=plan.reveal_allowed,
            drawing_actions=[dict(action) for action in plan.drawing_actions],
            expected_student_action=plan.expected_student_action,
            proposed_memory_updates=self._memory_proposals(inputs),
            # Honest reading of the verifier's result; the coordinator checks this anyway.
            step_assessment=plan.step_status,
            decision_justification=plan.decision_justification,
        )

    def _memory_proposals(self, inputs: DraftInputs) -> list[dict[str, object]]:
        plan = inputs.plan
        if plan.memory_hint == "session_tiredness" and plan.local_source_ids:
            return [
                CreateSessionContextProposal(
                    operation="create_session_context",
                    learner_id=inputs.learner_id,
                    session_id=inputs.session_id,
                    content="The learner said they are tired today; keep the pace light.",
                    evidence_kind="self_report",
                    confidence=0.9,
                    source_ids=[plan.local_source_ids[0]],
                    expires_at=inputs.now + SESSION_TIREDNESS_TTL,
                ).model_dump(mode="json")
            ]
        if plan.memory_hint == "assisted_success_note":
            return [
                CreateEpisodicNoteProposal(
                    operation="create_episodic_note",
                    learner_id=inputs.learner_id,
                    session_id=inputs.session_id,
                    content=(
                        "Solved with correct steps after a worked explanation; "
                        "independent transfer not yet seen."
                        if plan.message_params.get("revealed") == "yes"
                        else "Solved with correct steps after a grouping hint; "
                        "independent transfer not yet seen."
                    ),
                    evidence_kind="inference",
                    confidence=0.5,
                    source_ids=list(dict.fromkeys(plan.required_evidence_ids))[:8],
                    review_at=inputs.now + NOTE_REVIEW_DELAY,
                    expires_at=inputs.now + NOTE_LIFETIME,
                ).model_dump(mode="json")
            ]
        return []


__all__ = [
    "MOCK_LABEL",
    "DraftInputs",
    "MockTutorProvider",
    "ProviderLabel",
    "ProviderUnavailableError",
    "TutorProvider",
    "get_provider",
]


def get_provider(settings: Settings) -> TutorProvider:
    """The configured provider. Non-mock adapters are cached per process and built lazily."""
    if settings.tutor_provider == "mock":
        return MockTutorProvider()
    from app.inference.factory import adapter_for

    return adapter_for(settings)
