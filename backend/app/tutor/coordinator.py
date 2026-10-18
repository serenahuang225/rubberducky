"""Reserve, run and commit tutor turns with exactly-once local effects.

Flow per command: a short reserve transaction checks the expected session revision, records
the student's raw evidence, computes the deterministic plan, stores a ``pending`` turn under
the command's idempotency key and advances the session revision. Provider inference then
runs outside any transaction. A commit transaction rechecks the revision, validates the
draft against the plan, verifier and context, and applies text, hint, scene, memory and
derived BKT effects atomically. A retry with the same key replays the stored outcome (or
finishes a still-pending turn); the same key with different content conflicts; a turn whose
session moved on during inference is superseded without tutor-side effects.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from app.config import Settings
from app.db.database import Database
from app.db.models import AttemptRow, HintRow, SessionRow, TutorTurnRow
from app.db.repositories import ScopedRepository
from app.db.seed import EXPLANATION_PROBLEM_ID, FIXTURE_PROBLEM_ID
from app.inference.cancel import CancelToken
from app.inference.providers import DraftInputs, TutorProvider, get_provider
from app.inference.request import (
    InsufficientContextError,
    ProviderBudgetError,
    build_provider_request,
)
from app.learner.memory import episodic_notes
from app.learner.memory_updates import ProposalScope, apply_memory_updates
from app.learner.pairing import LearnerScope, new_id
from app.pedagogy.handhold import CONTROL_LABELS, HOLD_JUSTIFICATION, HOLD_NEXT, HOLD_TEACHING
from app.pedagogy.persona import effective_personality
from app.pedagogy.intents import HelpIntent
from app.pedagogy.policy import Persona, TurnPlan, WorkFacts, plan_check_in, plan_work
from app.pedagogy.problems import (
    TRANSFER_ORDER,
    ProblemSpec,
    UnknownProblemError,
    fresh_variant_reason,
    problem_spec,
)
from app.schemas.memory import MemoryUpdateResult
from app.schemas.tutor import (
    ApproachTrace,
    CheckInRequest,
    CommittedDrawing,
    HelpRequest,
    Pace,
    ProblemView,
    ProviderLabel,
    StudentInputOutcome,
    TurnRejection,
    TutorDraft,
    TutorTurnResult,
    WorkInputMode,
    WorkRequest,
)
from app.tracing.replay import replay_learner
from app.tutor.brought_question import (
    BroughtQuestion,
    BroughtQuestionError,
    follow_up_display,
    has_brought_question,
    is_learner_problem,
    open_learner_problem,
    place_teaching_note,
    read_brought_question,
    spec_for_stored_problem,
)
from app.tutor.cancellation import (
    EPOCH_CHANGED,
    INFLIGHT,
    RESTART_INTERRUPTED,
    REVISION_CHANGED,
    SUPERSEDED_BY_WORK,
    bump_epoch,
    current_epoch,
    settle_pending_turns,
)
from app.tutor.evidence import (
    ensure_attempt,
    ensure_statement_object,
    open_attempt,
    problem_view,
    record_approach_trace,
    record_check_in,
    record_help,
    record_work,
    statement_object_id,
)
from app.tutor.validation import citable_for_turn, validate_draft
from app.whiteboard.scene import retire_tutor_objects, visible_tutor_object_ids
from app.whiteboard.tools import apply_tool_actions

SYSTEM_TEXT = (
    "You are the Rubberducky algebra tutor for one learner in a private local prototype. "
    "Answer with a TutorDraft JSON object that follows the plan exactly: the public "
    "utterance, the cited evidence IDs, bounded drawing actions and memory proposals. "
    "Never reveal an answer or a completed step the learner has not produced, and cite "
    "only IDs that appear in the provided context."
)

MAX_TURN_EVENTS = 50


class TurnCommandError(Exception):
    """A command rejected before any turn effect; mapped to an HTTP error by the API layer."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class _Reserved:
    turn_id: str
    base_revision: int
    base_epoch: int
    plan: TurnPlan
    student_input: StudentInputOutcome


def _request_hash(kind: str, body: CheckInRequest | WorkRequest | HelpRequest) -> str:
    payload = json.dumps({"kind": kind, "body": body.model_dump(mode="json")}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_persona(database: Database, scope: LearnerScope) -> Persona:
    db = database.new_session()
    try:
        return _persona(ScopedRepository(db, scope))
    finally:
        db.close()


def _persona(repo: ScopedRepository) -> Persona:
    config = repo.tutor_configuration()
    if config is None:
        return Persona()
    return Persona(personality=config.personality, comfort_override=config.comfort_override)


def _spec_for_attempt(repo: ScopedRepository, attempt: AttemptRow) -> ProblemSpec:
    try:
        return spec_for_stored_problem(repo, attempt.problem_id)
    except UnknownProblemError as error:
        raise TurnCommandError(
            "no_active_problem", "The session's current problem is not available."
        ) from error


def _plan_check_in_turn(
    repo: ScopedRepository,
    session: SessionRow,
    body: CheckInRequest,
    turn_id: str,
    now: datetime,
    prepared: BroughtQuestion | None = None,
) -> tuple[TurnPlan, StudentInputOutcome]:
    observation_id, note = record_check_in(repo, session.id, turn_id, now)
    session.goal = "learner_question" if prepared is not None else body.goal
    attempt = open_attempt(repo, session.id)
    if attempt is None:
        if prepared is not None:
            spec, attempt, statement_id = open_learner_problem(repo, session.id, prepared, now)
        else:
            if body.goal == "learner_question":
                raise TurnCommandError(
                    "question_required",
                    "Type a question or attach a picture of it.",
                    422,
                )
            problem_id = (
                EXPLANATION_PROBLEM_ID
                if body.goal == "explain_distribution"
                else FIXTURE_PROBLEM_ID
            )
            spec = problem_spec(problem_id)
            attempt = ensure_attempt(repo, session.id, problem_id, now)
            statement_id = ensure_statement_object(repo, session.id, spec, now)
    else:
        if prepared is not None:
            raise TurnCommandError(
                "problem_already_open",
                "This session already has a question. Finish it or start a new session.",
                409,
            )
        spec = _spec_for_attempt(repo, attempt)
        statement_id = statement_object_id(session.id, spec.problem_id)
    problem = problem_view(spec, attempt.id, statement_id)
    hint_ids = set(
        repo.db.execute(select(HintRow.id).where(HintRow.learner_id == repo.learner_id)).scalars()
    )
    # A note whose periodic review is due is still the learner's real history; review
    # gates memory maintenance, not whether earlier assistance may inform instruction.
    notes = [n.entry for n in episodic_notes(repo, now) if n.entry.status == "active"]
    reminder_ids = [note.id for note in notes if set(note.source_ids) & hint_ids]
    plan = plan_check_in(
        turn_id=turn_id,
        spec=spec,
        problem=problem,
        energy=body.energy,
        check_in_observation_id=observation_id,
        reminder_ids=reminder_ids,
        persona=_persona(repo),
    )
    if prepared is not None:
        plan = plan.model_copy(
            update={
                "message_params": {
                    **plan.message_params,
                    "learner_authored": "yes",
                    "teaching": prepared.teaching,
                },
                "expected_student_action": prepared.next_step,
                "forbidden_disclosures": [],
                "decision_justification": (
                    "Claude read the question and wrote the note shown on the board."
                ),
            }
        )
    student_input = StudentInputOutcome(
        input_mode="check_in",
        text=None,
        classification="check_in",
        step_id=None,
        observation_ids=[observation_id],
        eligibility=[note],
    )
    return plan, student_input


def _learner_reply_plan(
    *,
    turn_id: str,
    spec: ProblemSpec,
    problem: ProblemView,
    recorded_ids: list[str],
    persona: Persona,
    pace: Pace,
    attempt_id: str,
    help_request: bool,
) -> TurnPlan:
    """A plan Claude may word, without the built-in algebra ladder or a known answer."""
    return TurnPlan(
        turn_id=turn_id,
        action_type="diagnostic_hint" if help_request else "step_feedback",
        tone="support",
        message_params={"statement": problem.statement, "learner_authored": "yes"},
        target_concept_ids=[spec.concept_id],
        context_concept_id=spec.step_concept_id,
        hint_level=1 if help_request else 0,
        forbidden_disclosures=[],
        required_evidence_ids=recorded_ids[:12],
        local_source_ids=[],
        expected_student_action="Read the note on the board, then try the next step.",
        drawing_actions=[],
        memory_hint="none",
        pace=pace,
        step_status=None,
        personality=persona.personality,
        comfort_override=persona.comfort_override,
        current_problem=problem,
        worked_attempt_id=attempt_id,
        decision_justification="Claude writes the note shown for the learner's own question.",
    )


def _hold_plan(
    *,
    turn_id: str,
    spec: ProblemSpec,
    problem: ProblemView,
    recorded_ids: list[str],
    persona: Persona,
    pace: Pace,
    attempt_id: str,
) -> TurnPlan:
    """They are still exploring: wait, and do not correct or confirm the work."""
    plan = _learner_reply_plan(
        turn_id=turn_id,
        spec=spec,
        problem=problem,
        recorded_ids=recorded_ids,
        persona=persona,
        pace=pace,
        attempt_id=attempt_id,
        help_request=False,
    )
    return plan.model_copy(
        update={
            "message_params": {
                **plan.message_params,
                "learner_authored": "yes" if is_learner_problem(spec.problem_id) else "no",
                "teaching": HOLD_TEACHING,
                "hold_for_exploration": "yes",
            },
            "expected_student_action": HOLD_NEXT,
            "hint_level": 0,
            "action_type": "step_feedback",
            "decision_justification": HOLD_JUSTIFICATION,
        }
    )


def _next_problem_after(problem_id: str) -> str | None:
    if problem_id == FIXTURE_PROBLEM_ID:
        return TRANSFER_ORDER[0]
    if problem_id in TRANSFER_ORDER:
        index = TRANSFER_ORDER.index(problem_id)
        if index + 1 < len(TRANSFER_ORDER):
            return TRANSFER_ORDER[index + 1]
        return EXPLANATION_PROBLEM_ID
    return None


def _fresh_next(spec: ProblemSpec) -> ProblemSpec | None:
    """The next problem after a verified solution, or None to wrap up.

    A transfer candidate is only offered when it genuinely changes numbers or form; the
    check runs even though the built-in sequence is fixed, so a future spec edit that
    introduces a renamed-only "variant" degrades to a wrap-up instead of a false transfer.
    """
    next_id = _next_problem_after(spec.problem_id)
    if next_id is None:
        return None
    candidate = problem_spec(next_id)
    if candidate.kind == "transfer" and fresh_variant_reason(spec, candidate) is not None:
        return None
    return candidate


def _plan_work_turn(
    repo: ScopedRepository,
    session: SessionRow,
    body: WorkRequest | HelpRequest,
    turn_id: str,
    now: datetime,
) -> tuple[TurnPlan, StudentInputOutcome]:
    attempt = open_attempt(repo, session.id)
    if attempt is None:
        raise TurnCommandError(
            "no_active_problem", "No problem is currently posed; check in first."
        )
    spec = _spec_for_attempt(repo, attempt)
    input_mode: WorkInputMode | Literal["help_button"]
    if isinstance(body, HelpRequest):
        input_mode = "help_button"
        learner_text = CONTROL_LABELS[body.learner_control]
        help_intent: HelpIntent = "explain_request" if body.mode == "explain" else "not_sure"
        recorded = record_help(repo, session.id, attempt, spec, help_intent, turn_id, now)
    else:
        input_mode = body.input_mode
        learner_text = body.text
        recorded = record_work(
            repo, session.id, attempt, spec, body.text, body.input_mode, now, turn_id
        )
    problem = problem_view(spec, attempt.id, statement_object_id(session.id, spec.problem_id))

    next_problem = None
    next_spec = None
    if recorded.analysis.classification == "solution_with_reasoning":
        next_spec = _fresh_next(spec)
        if next_spec is not None:
            next_problem = ProblemView(
                problem_id=next_spec.problem_id,
                # Generated now, created at commit, so a retried pending turn reuses it.
                attempt_id=new_id(),
                statement=next_spec.statement,
                kind=next_spec.kind,
                concept_id=next_spec.concept_id,
                statement_object_id=statement_object_id(session.id, next_spec.problem_id),
            )
    facts = WorkFacts(
        turn_id=turn_id,
        spec=spec,
        problem=problem,
        analysis=recorded.analysis,
        text=learner_text,
        step_id=recorded.step_id,
        observation_ids=recorded.observation_ids,
        attempt_hint_ids=recorded.attempt_hint_ids,
        attempt_hint_levels=recorded.attempt_hint_levels,
        expanded_seen=recorded.expanded_seen,
        hypothesis=recorded.hypothesis,
        assessment_observation_id=recorded.assessment_observation_id,
        next_problem=next_problem,
        next_spec=next_spec,
        explanation=recorded.explanation,
        explanation_missing=recorded.explanation_missing,
        attempt_answer_revealed=recorded.attempt_answer_revealed,
    )
    # Pace is a session-level property: a tiredness check-in lightens the whole session,
    # so work turns carry the pace of the latest committed turn rather than resetting.
    latest = repo.db.execute(
        select(TutorTurnRow)
        .where(
            TutorTurnRow.learner_id == repo.learner_id,
            TutorTurnRow.session_id == session.id,
            TutorTurnRow.status == "committed",
        )
        .order_by(TutorTurnRow.created_at.desc(), TutorTurnRow.id)
        .limit(1)
    ).scalar_one_or_none()
    pace: Pace = "standard"
    if latest is not None and latest.result.get("pace") == "lighter":
        pace = "lighter"
    persona = _persona(repo)
    if isinstance(body, HelpRequest) and body.learner_control == "still_exploring":
        plan = _hold_plan(
            turn_id=turn_id,
            spec=spec,
            problem=problem,
            recorded_ids=list(recorded.observation_ids),
            persona=persona,
            pace=pace,
            attempt_id=attempt.id,
        )
    elif is_learner_problem(spec.problem_id):
        plan = _learner_reply_plan(
            turn_id=turn_id,
            spec=spec,
            problem=problem,
            recorded_ids=list(recorded.observation_ids),
            persona=persona,
            pace=pace,
            attempt_id=attempt.id,
            help_request=isinstance(body, HelpRequest),
        )
    else:
        plan = plan_work(facts, persona).model_copy(
            update={"worked_attempt_id": attempt.id, "pace": pace}
        )
    student_input = StudentInputOutcome(
        input_mode=input_mode,
        text=learner_text,
        classification=recorded.analysis.classification,
        step_id=recorded.step_id,
        observation_ids=list(recorded.observation_ids),
        assessment_id=recorded.assessment_id,
        assessment_kind=recorded.assessment_kind,
        assessment_independent=recorded.assessment_independent,
        verification=recorded.analysis.verification,
        reasoning_assessment=recorded.analysis.reasoning,
        explanation_judgment=recorded.explanation,
        eligibility=list(recorded.eligibility),
    )
    return plan, student_input


def _reserve(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    kind: str,
    body: CheckInRequest | WorkRequest | HelpRequest,
    idempotency_key: str,
    label: ProviderLabel,
    now: datetime,
    prepared: BroughtQuestion | None = None,
) -> _Reserved | TutorTurnResult:
    withdrawn: list[str] = []
    try:
        outcome = _reserve_in_transaction(
            database,
            scope,
            session_id,
            kind,
            body,
            idempotency_key,
            label,
            now,
            withdrawn,
            prepared,
        )
    except TurnCommandError as error:
        if error.code != "revision_conflict":
            raise
        # A simultaneous identical retry may have just reserved this very key; look again so
        # it replays that turn instead of reporting a conflict with itself.
        outcome = _reserve_in_transaction(
            database,
            scope,
            session_id,
            kind,
            body,
            idempotency_key,
            label,
            now,
            withdrawn,
            prepared,
        )
    # Cooperative provider cancel only after the withdrawal is durable.
    INFLIGHT.cancel(withdrawn, "superseded")
    return outcome


def _resume_after_restart(row: TutorTurnRow, session: SessionRow) -> TutorTurnResult | None:
    """The stored pending form of a restart-failed turn that may still be finished, else None."""
    stored = TutorTurnResult.model_validate(row.result)
    interrupted = any(r.code == RESTART_INTERRUPTED.code for r in stored.rejections)
    if (
        row.status != "failed"
        or not interrupted
        or session.revision != row.base_revision + 1
        or session.status != "active"
    ):
        return None
    return stored.model_copy(
        update={
            "status": "pending",
            "rejections": [],
            "completed_at": None,
            "cancellation_epoch": session.cancellation_epoch,
        }
    )


def _reserve_in_transaction(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    kind: str,
    body: CheckInRequest | WorkRequest | HelpRequest,
    idempotency_key: str,
    label: ProviderLabel,
    now: datetime,
    withdrawn: list[str],
    prepared: BroughtQuestion | None = None,
) -> _Reserved | TutorTurnResult:
    request_hash = _request_hash(kind, body)
    # A Help press is stored as a work turn: it records learner input for the open problem.
    row_kind = "work" if kind == "help" else kind
    with database.transaction() as db:
        repo = ScopedRepository(db, scope)
        session = repo.require_session(session_id)
        if session.status != "active":
            raise TurnCommandError("session_not_active", "The session is not active.")
        existing = repo.db.execute(
            select(TutorTurnRow).where(
                TutorTurnRow.learner_id == scope.learner_id,
                TutorTurnRow.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash or existing.kind != row_kind:
                raise TurnCommandError(
                    "idempotency_conflict",
                    "This idempotency key was already used with different content.",
                )
            stored = TutorTurnResult.model_validate(existing.result)
            resumed = _resume_after_restart(existing, session)
            if resumed is not None:
                # The process died mid-turn and the client never saw an answer: finish the
                # same reserved turn (same plan, same recorded evidence) exactly once.
                existing.status = "pending"
                existing.completed_at = None
                existing.base_epoch = session.cancellation_epoch
                existing.result = resumed.model_dump(mode="json")
                repo.db.flush()
                stored = resumed
            elif existing.status != "pending":
                return stored.model_copy(update={"replayed": True})
            # A previous request crashed after reserving: finish the same plan now.
            return _Reserved(
                turn_id=existing.id,
                base_revision=existing.base_revision,
                base_epoch=existing.base_epoch,
                plan=TurnPlan.model_validate(existing.plan),
                student_input=stored.student_input,  # type: ignore[arg-type]
            )
        if body.expected_revision != session.revision:
            raise TurnCommandError(
                "revision_conflict",
                f"The session is at revision {session.revision}, not {body.expected_revision}.",
            )
        # Claim the revision atomically before recording anything: a concurrent command
        # blocks on the write lock and then fails this compare-and-swap instead of
        # double-booking evidence under a stale snapshot.
        bumped_result = repo.db.execute(
            update(SessionRow)
            .where(
                SessionRow.id == session_id,
                SessionRow.learner_id == scope.learner_id,
                SessionRow.revision == body.expected_revision,
                SessionRow.status == "active",
            )
            .values(revision=SessionRow.revision + 1),
            execution_options={"synchronize_session": False},
        )
        bumped = cast(CursorResult[Any], bumped_result).rowcount
        if bumped != 1:
            raise TurnCommandError(
                "revision_conflict",
                "The session changed while this command was being reserved; retry.",
            )
        session.revision = body.expected_revision + 1
        # Newer work replaces any reply still being prepared; withdraw it before the new turn
        # records its own evidence so only one reply can ever land for the current state.
        withdrawn += settle_pending_turns(
            repo,
            session_id,
            status="superseded",
            rejection=SUPERSEDED_BY_WORK,
            now=now,
            replay=False,
        )
        base_epoch = current_epoch(repo, session_id)
        turn_id = new_id()
        if kind == "check_in":
            assert isinstance(body, CheckInRequest)  # noqa: S101 - narrowed by caller
            plan, student_input = _plan_check_in_turn(
                repo, session, body, turn_id, now, prepared
            )
        else:
            assert isinstance(body, WorkRequest | HelpRequest)  # noqa: S101 - narrowed by caller
            plan, student_input = _plan_work_turn(repo, session, body, turn_id, now)
        # The compare-and-swap above already advanced the stored revision.
        base_revision = body.expected_revision
        pending = TutorTurnResult(
            turn_id=turn_id,
            session_id=session_id,
            kind=row_kind,  # type: ignore[arg-type]
            status="pending",
            base_revision=base_revision,
            session_revision=base_revision + 1,
            cancellation_epoch=base_epoch,
            provider=label,
            student_input=student_input,
            current_problem=plan.current_problem,
            pace=plan.pace,
            action_type=plan.action_type,
            expected_student_action=plan.expected_student_action,
            target_concept_ids=list(plan.target_concept_ids),
            created_at=now,
        )
        repo.db.add(
            TutorTurnRow(
                id=turn_id,
                schema_version="tutor-turn.v1",
                learner_id=scope.learner_id,
                session_id=session_id,
                kind=row_kind,
                status="pending",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                base_revision=base_revision,
                base_epoch=base_epoch,
                committed_revision=None,
                provider=label.name,
                is_mock=label.is_mock,
                plan=plan.model_dump(mode="json"),
                result=pending.model_dump(mode="json"),
                created_at=now,
                completed_at=None,
            )
        )
        repo.db.flush()
        return _Reserved(
            turn_id=turn_id,
            base_revision=base_revision,
            base_epoch=base_epoch,
            plan=plan,
            student_input=student_input,
        )


def _learner_text(body: CheckInRequest | WorkRequest | HelpRequest) -> str:
    if isinstance(body, CheckInRequest):
        question = (body.question_text or "").strip()
        if question:
            return f"Check-in question: {question[:500]}"
        if body.question_image_base64 is not None:
            return "Check-in question: a picture of the learner's question."
        return f"Check-in: goal={body.goal}; energy={body.energy or 'not said'}."
    if isinstance(body, HelpRequest):
        label = CONTROL_LABELS[body.learner_control]
        if label:
            return f"[help_button] {label}"
        return f"[help_button] mode={body.mode}"
    return f"[{body.input_mode}] {body.text}"


def _draft_from_teaching(
    plan: TurnPlan,
    session_revision: int,
    teaching: str,
    next_step: str,
    *,
    approach: str = "",
    contradiction: str = "",
    explained_failure: bool = False,
) -> TutorDraft:
    """Package Claude's displayed note as a draft that matches the stored plan."""
    return TutorDraft(
        turn_id=plan.turn_id,
        session_revision=session_revision,
        action_type=plan.action_type,
        utterance=teaching,
        target_concept_ids=list(plan.target_concept_ids),
        evidence_ids=list(dict.fromkeys(plan.required_evidence_ids)),
        hint_level=plan.hint_level,
        answer_revealed=plan.reveal_allowed,
        drawing_actions=[dict(action) for action in plan.drawing_actions],
        expected_student_action=next_step,
        proposed_memory_updates=[],
        step_assessment=plan.step_status,
        decision_justification=plan.decision_justification,
        approach=approach[:200],
        contradiction=contradiction[:200],
        explained_failure=explained_failure,
    )


def _infer(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    reserved: _Reserved,
    body: CheckInRequest | WorkRequest | HelpRequest,
    provider: TutorProvider,
    now: datetime,
    cancel: CancelToken,
    settings: Settings,
) -> tuple[TutorDraft, list[str]]:
    """Build the bounded context and ask the provider. Holds no transaction open."""
    if reserved.plan.message_params.get("hold_for_exploration") == "yes":
        teaching = reserved.plan.message_params.get("teaching") or HOLD_TEACHING
        return (
            _draft_from_teaching(
                reserved.plan,
                reserved.base_revision + 1,
                teaching,
                reserved.plan.expected_student_action,
            ),
            list(reserved.plan.required_evidence_ids),
        )
    if reserved.plan.message_params.get("learner_authored") == "yes":
        return _infer_brought_question(database, scope, session_id, reserved, body, settings), list(
            reserved.plan.required_evidence_ids
        )
    db = database.new_session()
    try:
        repo = ScopedRepository(db, scope)
        request, context = build_provider_request(
            repo,
            concept_id=reserved.plan.context_concept_id,
            now=now,
            system_text=SYSTEM_TEXT,
            user_text=_learner_text(body),
            session_id=session_id,
        )
    finally:
        db.close()
    draft = provider.draft(
        DraftInputs(
            plan=reserved.plan,
            request=request,
            context=context,
            learner_id=scope.learner_id,
            session_id=session_id,
            session_revision=reserved.base_revision + 1,
            learner_text=_learner_text(body),
            now=now,
            cancel=cancel,
        )
    )
    return draft, list(context.citable_ids)


def _infer_brought_question(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    reserved: _Reserved,
    body: CheckInRequest | WorkRequest | HelpRequest,
    settings: Settings,
) -> TutorDraft:
    """Use the note already written at check-in, or ask Claude for the next one to display."""
    plan = reserved.plan
    teaching = plan.message_params.get("teaching")
    next_step = plan.expected_student_action
    if not teaching:
        statement = plan.current_problem.statement if plan.current_problem is not None else ""
        prior = _latest_utterance(database, scope, session_id)
        if isinstance(body, HelpRequest):
            learner_text = CONTROL_LABELS[body.learner_control] or (
                "They pressed Help me and want the next idea shown on the board."
            )
        elif isinstance(body, WorkRequest):
            learner_text = body.text
        else:
            learner_text = (body.question_text or "").strip()
        handhold = body.handhold if isinstance(body, HelpRequest | WorkRequest) else "balanced"
        control = body.learner_control if isinstance(body, HelpRequest) else "none"
        displayed = follow_up_display(
            settings,
            statement=statement,
            learner_text=learner_text,
            prior_note=prior,
            handhold=handhold,
            control=control,
            personality=effective_personality(plan.personality, plan.comfort_override),
        )
        teaching = displayed.teaching
        next_step = displayed.next_step
        return _draft_from_teaching(
            plan,
            reserved.base_revision + 1,
            teaching,
            next_step,
            approach=displayed.approach,
            contradiction=displayed.contradiction,
            explained_failure=displayed.explained_failure,
        )
    return _draft_from_teaching(plan, reserved.base_revision + 1, teaching, next_step)


def _latest_utterance(database: Database, scope: LearnerScope, session_id: str) -> str | None:
    db = database.new_session()
    try:
        repo = ScopedRepository(db, scope)
        latest = repo.db.execute(
            select(TutorTurnRow)
            .where(
                TutorTurnRow.learner_id == scope.learner_id,
                TutorTurnRow.session_id == session_id,
                TutorTurnRow.status == "committed",
            )
            .order_by(TutorTurnRow.created_at.desc(), TutorTurnRow.id)
            .limit(1)
        ).scalar_one_or_none()
    finally:
        db.close()
    if latest is None:
        return None
    utterance = latest.result.get("utterance")
    return utterance if isinstance(utterance, str) and utterance else None


def _label(row: TutorTurnRow, provider: TutorProvider) -> ProviderLabel:
    return ProviderLabel(name=row.provider, is_mock=row.is_mock, label=provider.label().label)


def _fill_update_status(
    student_input: StudentInputOutcome | None, updates: Mapping[str, str]
) -> StudentInputOutcome | None:
    if student_input is None:
        return None
    return student_input.model_copy(
        update={
            "eligibility": [
                note.model_copy(update={"update_status": updates.get(note.observation_id)})
                for note in student_input.eligibility
            ]
        }
    )


def _commit(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    reserved: _Reserved,
    body: CheckInRequest | WorkRequest | HelpRequest,
    draft: TutorDraft | None,
    draft_error: TurnRejection | None,
    citable_ids: list[str],
    provider: TutorProvider,
    now: datetime,
) -> TutorTurnResult:
    with database.transaction() as db:
        repo = ScopedRepository(db, scope)
        # Take the write lock before reading anything the commit decides on: scope, revision,
        # epoch and turn status are then rechecked against state no other writer can change
        # until this transaction ends, so two completions of one turn cannot both apply.
        db.execute(
            update(TutorTurnRow)
            .where(
                TutorTurnRow.id == reserved.turn_id,
                TutorTurnRow.learner_id == scope.learner_id,
                TutorTurnRow.status == "pending",
            )
            .values(completed_at=TutorTurnRow.completed_at)
            .execution_options(synchronize_session=False)
        )
        row = repo.db.execute(
            select(TutorTurnRow).where(
                TutorTurnRow.id == reserved.turn_id,
                TutorTurnRow.learner_id == scope.learner_id,
            )
        ).scalar_one_or_none()
        if row is None:
            # The session or profile was deleted while the provider was drafting.
            raise TurnCommandError("turn_removed", "This turn's records were deleted.")
        if row.status != "pending":
            # A concurrent completion of the same turn already committed; replay it.
            return TutorTurnResult.model_validate(row.result).model_copy(update={"replayed": True})
        session = repo.require_session(session_id)
        plan = TurnPlan.model_validate(row.plan)
        student_input = TutorTurnResult.model_validate(row.result).student_input
        status: str
        rejections: list[TurnRejection] = []
        hint_id: str | None = None
        drawings: list[CommittedDrawing] = []
        memory: MemoryUpdateResult | None = None
        committed = False

        if session.revision != row.base_revision + 1 or session.status != "active":
            status = "superseded"
            rejections = [REVISION_CHANGED]
        elif session.cancellation_epoch != row.base_epoch:
            status = "superseded"
            rejections = [EPOCH_CHANGED]
        elif draft_error is not None:
            status = "failed"
            rejections = [draft_error]
            assert draft is None  # noqa: S101 - paired by the caller
        else:
            assert draft is not None  # noqa: S101 - paired by the caller
            actions, rejections = validate_draft(
                repo, session_id, plan, draft, citable_ids, row.base_revision
            )
            if not rejections:
                memory = apply_memory_updates(
                    repo,
                    draft.proposed_memory_updates,
                    ProposalScope(
                        session_id=session_id,
                        turn_id=row.id,
                        citable_source_ids=citable_for_turn(citable_ids, plan),
                    ),
                    now,
                )
                if memory.status == "rejected":
                    rejections = [
                        TurnRejection(code=item.code, message=item.message)
                        for item in memory.rejections
                    ]
                    memory = None
            if rejections:
                status = "rejected"
            else:
                status = "committed"
                committed = True
                if draft.hint_level > 0:
                    hint_id = new_id()
                    repo.db.add(
                        HintRow(
                            id=hint_id,
                            schema_version="hint.v1",
                            learner_id=scope.learner_id,
                            session_id=session_id,
                            attempt_id=(
                                plan.current_problem.attempt_id
                                if plan.current_problem is not None
                                else None
                            ),
                            concept_id=plan.target_concept_ids[0],
                            level=draft.hint_level,
                            answer_revealed=draft.answer_revealed,
                            content=draft.utterance[:500],
                            provenance="submitted",
                            given_at=now,
                        )
                    )
                transition = (
                    plan.worked_attempt_id is not None
                    and plan.current_problem is not None
                    and plan.current_problem.attempt_id != plan.worked_attempt_id
                )
                # Captured before this turn adds anything, so only earlier tutor marks retire.
                superseded_marks = visible_tutor_object_ids(repo, session_id) if transition else []
                applied = apply_tool_actions(repo, session_id, row.id, actions, now)
                drawings = [
                    CommittedDrawing(
                        object_id=item.object_id,
                        tool=item.tool,
                        semantic_role=item.semantic_role,
                    )
                    for item in applied
                ]
                if plan.message_params.get("learner_authored") == "yes":
                    note_id = place_teaching_note(repo, session_id, row.id, draft.utterance, now)
                    drawings.append(
                        CommittedDrawing(
                            object_id=note_id, tool="text", semantic_role="teaching_note"
                        )
                    )
                if (
                    plan.worked_attempt_id is not None
                    and plan.current_problem is not None
                    and plan.current_problem.attempt_id != plan.worked_attempt_id
                ):
                    worked = repo.db.get(AttemptRow, plan.worked_attempt_id)
                    if worked is not None and worked.completed_at is None:
                        worked.completed_at = now
                    next_spec = problem_spec(plan.current_problem.problem_id)
                    if repo.db.get(AttemptRow, plan.current_problem.attempt_id) is None:
                        ensure_attempt(
                            repo,
                            session_id,
                            plan.current_problem.problem_id,
                            now,
                            attempt_id=plan.current_problem.attempt_id,
                        )
                    new_statement_id = ensure_statement_object(repo, session_id, next_spec, now)
                    # Both statements are posed at the same board position, so the earlier
                    # problem's tutor marks leave the view (logged, never student work).
                    retire_tutor_objects(
                        repo,
                        session_id,
                        [i for i in superseded_marks if i != new_statement_id],
                        now,
                    )
                    bump_epoch(repo, session_id)
                repo.db.flush()

        # Derived BKT state follows the raw evidence recorded at reserve, whatever the
        # provider outcome was; replay is deterministic and rewrites derived rows wholesale.
        _, report = replay_learner(db, scope.learner_id, now)
        update_status = {u.observation_id: u.status for u in report.updates}
        student_input = _fill_update_status(student_input, update_status)

        approach_trace = None
        hypothesis = plan.hypothesis if committed else None
        if committed and draft is not None and draft.approach.strip():
            approach_trace = ApproachTrace(
                approach=draft.approach.strip()[:200],
                contradiction=draft.contradiction.strip()[:200] or None,
                explained_failure=draft.explained_failure,
            )
            observation_id = (
                student_input.observation_ids[0]
                if student_input is not None and student_input.observation_ids
                else None
            )
            if observation_id is not None:
                hypothesis = record_approach_trace(
                    repo,
                    session_id=session_id,
                    concept_id=plan.context_concept_id,
                    observation_id=observation_id,
                    approach=approach_trace.approach,
                    contradiction=approach_trace.contradiction,
                    explained_failure=approach_trace.explained_failure,
                    now=now,
                )
            plan = plan.model_copy(
                update={
                    "message_params": {
                        **plan.message_params,
                        "approach": approach_trace.approach,
                        "contradiction": approach_trace.contradiction or "",
                        "explained_failure": "yes" if approach_trace.explained_failure else "no",
                    }
                }
            )
            row.plan = plan.model_dump(mode="json")

        result = TutorTurnResult(
            turn_id=row.id,
            session_id=session_id,
            kind=row.kind,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            base_revision=row.base_revision,
            session_revision=row.base_revision + 1,
            cancellation_epoch=current_epoch(repo, session_id),
            provider=_label(row, provider),
            student_input=student_input,
            current_problem=plan.current_problem,
            pace=plan.pace,
            action_type=plan.action_type,
            utterance=draft.utterance if committed and draft is not None else None,
            expected_student_action=(
                draft.expected_student_action
                if committed
                and draft is not None
                and plan.message_params.get("learner_authored") == "yes"
                else plan.expected_student_action
            ),
            target_concept_ids=list(plan.target_concept_ids),
            evidence_ids=list(draft.evidence_ids) if committed and draft is not None else [],
            hypothesis=hypothesis,
            hint_id=hint_id,
            hint_level=draft.hint_level if committed and draft is not None else 0,
            answer_revealed=committed and draft is not None and draft.answer_revealed,
            representation=plan.representation if committed else None,
            support_change=plan.support_change if committed else "none",
            drawings=drawings,
            memory=memory,
            decision_justification=(
                draft.decision_justification if committed and draft is not None else None
            ),
            approach_trace=approach_trace,
            context_source_ids=sorted(citable_ids) if committed else [],
            rejections=rejections,
            replayed=False,
            created_at=row.created_at,
            completed_at=now,
        )
        row.status = status
        row.completed_at = now
        row.result = result.model_dump(mode="json")
        if committed:
            row.committed_revision = row.base_revision + 1
        repo.db.flush()
        return result


def _idempotency_known(database: Database, scope: LearnerScope, idempotency_key: str) -> bool:
    """True when this key already reserved a turn, so a retry must not call Claude again."""
    with database.transaction() as db:
        repo = ScopedRepository(db, scope)
        existing = repo.db.execute(
            select(TutorTurnRow.id).where(
                TutorTurnRow.learner_id == scope.learner_id,
                TutorTurnRow.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
    return existing is not None


def _require_claude(settings: Settings) -> None:
    if settings.tutor_provider != "claude" or not settings.external_integrations_enabled:
        raise TurnCommandError(
            "tutor_not_configured",
            "Showing your own question needs the Claude tutor. "
            "The server is still on the scripted tutor.",
            503,
        )


def execute_turn(
    database: Database,
    scope: LearnerScope,
    settings: Settings,
    session_id: str,
    kind: str,
    body: CheckInRequest | WorkRequest | HelpRequest,
    idempotency_key: str,
    now: datetime,
) -> TutorTurnResult:
    """Run one tutor command end to end (reserve, infer outside transactions, commit)."""
    prepared: BroughtQuestion | None = None
    if (
        isinstance(body, CheckInRequest)
        and has_brought_question(body)
        and not _idempotency_known(database, scope, idempotency_key)
    ):
        _require_claude(settings)
        try:
            persona = _load_persona(database, scope)
            prepared = read_brought_question(
                settings,
                body,
                personality=effective_personality(persona.personality, persona.comfort_override),
            )
        except BroughtQuestionError as error:
            raise TurnCommandError("provider_error", error.message, 502) from error
    provider = get_provider(settings)
    reserved = _reserve(
        database,
        scope,
        session_id,
        kind,
        body,
        idempotency_key,
        provider.label(),
        now,
        prepared,
    )
    if isinstance(reserved, TutorTurnResult):
        return reserved
    draft: TutorDraft | None = None
    draft_error: TurnRejection | None = None
    citable_ids: list[str] = []
    token = INFLIGHT.register(reserved.turn_id)
    try:
        draft, citable_ids = _infer(
            database, scope, session_id, reserved, body, provider, now, token, settings
        )
    except BroughtQuestionError as error:
        draft_error = TurnRejection(code="provider_error", message=error.message[:200])
    except (InsufficientContextError, ProviderBudgetError) as error:
        draft_error = TurnRejection(
            code="context_does_not_fit",
            message=f"The bounded request cannot be assembled honestly: {error}"[:200],
        )
    except Exception as error:
        draft_error = TurnRejection(
            code="provider_error",
            message=f"The provider failed to produce a usable draft ({type(error).__name__}).",
        )
    finally:
        INFLIGHT.release(reserved.turn_id)
    return _commit(
        database,
        scope,
        session_id,
        reserved,
        body,
        draft,
        draft_error,
        citable_ids,
        provider,
        now,
    )
