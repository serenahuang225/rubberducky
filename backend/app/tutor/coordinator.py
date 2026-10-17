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
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from app.config import Settings
from app.db.database import Database
from app.db.models import AttemptRow, HintRow, SessionRow, TutorTurnRow
from app.db.repositories import ScopedRepository
from app.db.seed import EXPLANATION_PROBLEM_ID, FIXTURE_PROBLEM_ID
from app.inference.providers import DraftInputs, TutorProvider, get_provider
from app.inference.request import (
    InsufficientContextError,
    ProviderBudgetError,
    build_provider_request,
)
from app.learner.memory import episodic_notes
from app.learner.memory_updates import ProposalScope, apply_memory_updates
from app.learner.pairing import LearnerScope, new_id
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
    CheckInRequest,
    CommittedDrawing,
    ProblemView,
    ProviderLabel,
    StudentInputOutcome,
    TurnRejection,
    TutorDraft,
    TutorTurnResult,
    WorkRequest,
)
from app.tracing.replay import replay_learner
from app.tutor.evidence import (
    ensure_attempt,
    ensure_statement_object,
    open_attempt,
    problem_view,
    record_check_in,
    record_work,
    statement_object_id,
)
from app.tutor.validation import citable_for_turn, validate_draft
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
    plan: TurnPlan
    student_input: StudentInputOutcome


def _request_hash(kind: str, body: CheckInRequest | WorkRequest) -> str:
    payload = json.dumps({"kind": kind, "body": body.model_dump(mode="json")}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _persona(repo: ScopedRepository) -> Persona:
    config = repo.tutor_configuration()
    if config is None:
        return Persona()
    return Persona(personality=config.personality, comfort_override=config.comfort_override)


def _spec_for_attempt(attempt: AttemptRow) -> ProblemSpec:
    try:
        return problem_spec(attempt.problem_id)
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
) -> tuple[TurnPlan, StudentInputOutcome]:
    observation_id, note = record_check_in(repo, session.id, turn_id, now)
    session.goal = body.goal
    attempt = open_attempt(repo, session.id)
    if attempt is None:
        problem_id = (
            EXPLANATION_PROBLEM_ID
            if body.goal == "explain_distribution"
            else FIXTURE_PROBLEM_ID
        )
        spec = problem_spec(problem_id)
        attempt = ensure_attempt(repo, session.id, problem_id, now)
        statement_id = ensure_statement_object(repo, session.id, spec, now)
    else:
        spec = _spec_for_attempt(attempt)
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
    student_input = StudentInputOutcome(
        input_mode="check_in",
        text=None,
        classification="check_in",
        step_id=None,
        observation_ids=[observation_id],
        eligibility=[note],
    )
    return plan, student_input


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
    body: WorkRequest,
    turn_id: str,
    now: datetime,
) -> tuple[TurnPlan, StudentInputOutcome]:
    attempt = open_attempt(repo, session.id)
    if attempt is None:
        raise TurnCommandError(
            "no_active_problem", "No problem is currently posed; check in first."
        )
    spec = _spec_for_attempt(attempt)
    recorded = record_work(repo, session.id, attempt, spec, body.text, body.input_mode, now)
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
        text=body.text,
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
    pace = "standard"
    if latest is not None and latest.result.get("pace") == "lighter":
        pace = "lighter"
    plan = plan_work(facts, _persona(repo)).model_copy(
        update={"worked_attempt_id": attempt.id, "pace": pace}
    )
    student_input = StudentInputOutcome(
        input_mode=body.input_mode,
        text=body.text,
        classification=recorded.analysis.classification,
        step_id=recorded.step_id,
        observation_ids=list(recorded.observation_ids),
        assessment_id=recorded.assessment_id,
        assessment_kind=recorded.assessment_kind,
        assessment_independent=recorded.assessment_independent,
        verification=recorded.analysis.verification,
        explanation_judgment=recorded.explanation,
        eligibility=list(recorded.eligibility),
    )
    return plan, student_input


def _reserve(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    kind: str,
    body: CheckInRequest | WorkRequest,
    idempotency_key: str,
    label: ProviderLabel,
    now: datetime,
) -> _Reserved | TutorTurnResult:
    request_hash = _request_hash(kind, body)
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
            if existing.request_hash != request_hash or existing.kind != kind:
                raise TurnCommandError(
                    "idempotency_conflict",
                    "This idempotency key was already used with different content.",
                )
            stored = TutorTurnResult.model_validate(existing.result)
            if existing.status != "pending":
                return stored.model_copy(update={"replayed": True})
            # A previous request crashed after reserving: finish the same plan now.
            return _Reserved(
                turn_id=existing.id,
                base_revision=existing.base_revision,
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
        turn_id = new_id()
        if kind == "check_in":
            assert isinstance(body, CheckInRequest)  # noqa: S101 - narrowed by caller
            plan, student_input = _plan_check_in_turn(repo, session, body, turn_id, now)
        else:
            assert isinstance(body, WorkRequest)  # noqa: S101 - narrowed by caller
            plan, student_input = _plan_work_turn(repo, session, body, turn_id, now)
        # The compare-and-swap above already advanced the stored revision.
        base_revision = body.expected_revision
        pending = TutorTurnResult(
            turn_id=turn_id,
            session_id=session_id,
            kind=kind,  # type: ignore[arg-type]
            status="pending",
            base_revision=base_revision,
            session_revision=base_revision + 1,
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
                kind=kind,
                status="pending",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                base_revision=base_revision,
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
            plan=plan,
            student_input=student_input,
        )


def _learner_text(body: CheckInRequest | WorkRequest) -> str:
    if isinstance(body, CheckInRequest):
        return f"Check-in: goal={body.goal}; energy={body.energy or 'not said'}."
    return f"[{body.input_mode}] {body.text}"


def _infer(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    reserved: _Reserved,
    body: CheckInRequest | WorkRequest,
    provider: TutorProvider,
    now: datetime,
) -> tuple[TutorDraft, list[str]]:
    """Build the bounded context and ask the provider. Holds no transaction open."""
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
        )
    )
    return draft, list(context.citable_ids)


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
    body: CheckInRequest | WorkRequest,
    draft: TutorDraft | None,
    draft_error: TurnRejection | None,
    citable_ids: list[str],
    provider: TutorProvider,
    now: datetime,
) -> TutorTurnResult:
    with database.transaction() as db:
        repo = ScopedRepository(db, scope)
        row = repo.db.execute(
            select(TutorTurnRow).where(
                TutorTurnRow.id == reserved.turn_id,
                TutorTurnRow.learner_id == scope.learner_id,
            )
        ).scalar_one()
        if row.status != "pending":
            # A concurrent completion of the same turn already committed; replay it.
            return TutorTurnResult.model_validate(row.result).model_copy(
                update={"replayed": True}
            )
        session = repo.require_session(session_id)
        plan = TurnPlan.model_validate(row.plan)
        student_input = TutorTurnResult.model_validate(row.result).student_input
        status: str
        rejections: list[TurnRejection] = []
        hint_id: str | None = None
        drawings: list[CommittedDrawing] = []
        memory: MemoryUpdateResult | None = None
        committed = False

        if session.revision != row.base_revision + 1:
            status = "superseded"
            rejections = [
                TurnRejection(
                    code="revision_changed",
                    message="The session changed while this turn was being prepared.",
                )
            ]
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
                            answer_revealed=False,
                            content=draft.utterance[:500],
                            provenance="submitted",
                            given_at=now,
                        )
                    )
                applied = apply_tool_actions(repo, session_id, row.id, actions, now)
                drawings = [
                    CommittedDrawing(
                        object_id=item.object_id,
                        tool=item.tool,
                        semantic_role=item.semantic_role,
                    )
                    for item in applied
                ]
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
                    ensure_statement_object(repo, session_id, next_spec, now)
                repo.db.flush()

        # Derived BKT state follows the raw evidence recorded at reserve, whatever the
        # provider outcome was; replay is deterministic and rewrites derived rows wholesale.
        _, report = replay_learner(db, scope.learner_id, now)
        update_status = {u.observation_id: u.status for u in report.updates}
        student_input = _fill_update_status(student_input, update_status)

        result = TutorTurnResult(
            turn_id=row.id,
            session_id=session_id,
            kind=row.kind,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            base_revision=row.base_revision,
            session_revision=row.base_revision + 1,
            provider=_label(row, provider),
            student_input=student_input,
            current_problem=plan.current_problem,
            pace=plan.pace,
            action_type=plan.action_type,
            utterance=draft.utterance if committed and draft is not None else None,
            expected_student_action=plan.expected_student_action,
            target_concept_ids=list(plan.target_concept_ids),
            evidence_ids=list(draft.evidence_ids) if committed and draft is not None else [],
            hypothesis=plan.hypothesis if committed else None,
            hint_id=hint_id,
            hint_level=draft.hint_level if committed and draft is not None else 0,
            answer_revealed=False,
            drawings=drawings,
            memory=memory,
            decision_justification=(
                draft.decision_justification if committed and draft is not None else None
            ),
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


def execute_turn(
    database: Database,
    scope: LearnerScope,
    settings: Settings,
    session_id: str,
    kind: str,
    body: CheckInRequest | WorkRequest,
    idempotency_key: str,
    now: datetime,
) -> TutorTurnResult:
    """Run one tutor command end to end (reserve, infer outside transactions, commit)."""
    provider = get_provider(settings)
    reserved = _reserve(
        database, scope, session_id, kind, body, idempotency_key, provider.label(), now
    )
    if isinstance(reserved, TutorTurnResult):
        return reserved
    draft: TutorDraft | None = None
    draft_error: TurnRejection | None = None
    citable_ids: list[str] = []
    try:
        draft, citable_ids = _infer(database, scope, session_id, reserved, body, provider, now)
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
