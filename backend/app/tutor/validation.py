"""Validate a provider draft against the deterministic plan before anything is committed.

Every check compares the draft with server-side ground truth: the plan's action, hint level
and forbidden disclosures, the bounded context's citable IDs, the typed drawing tools and
the verifier's status. Any rejection discards the whole draft; a provider can never widen
its own permissions, disclose an unrevealed answer, or override verification.
"""

from collections.abc import Iterable

from app.db.repositories import ScopedRepository
from app.pedagogy.policy import TurnPlan, normalize
from app.schemas.tutor import TurnRejection, TutorDraft
from app.whiteboard.tools import ToolAction, text_of_actions, validate_tool_actions


def citable_for_turn(context_citable_ids: Iterable[str], plan: TurnPlan) -> frozenset[str]:
    """IDs a draft may cite: the context it saw plus records this turn itself created."""
    return frozenset(
        set(context_citable_ids) | set(plan.local_source_ids) | set(plan.required_evidence_ids)
    )


def _disclosures(plan: TurnPlan, texts: Iterable[str]) -> list[TurnRejection]:
    forbidden = [item for item in plan.forbidden_disclosures if item]
    rejections: list[TurnRejection] = []
    for text in texts:
        normalized = normalize(text)
        if any(item in normalized for item in forbidden):
            rejections.append(
                TurnRejection(
                    code="forbidden_disclosure",
                    message=(
                        "the draft shows an answer or completed step the learner has not produced"
                    ),
                )
            )
    return rejections


def validate_draft(
    repo: ScopedRepository,
    session_id: str,
    plan: TurnPlan,
    draft: TutorDraft,
    context_citable_ids: Iterable[str],
    base_revision: int,
) -> tuple[list[ToolAction], list[TurnRejection]]:
    """Check a draft; returns the validated drawing actions or the rejections (never both used)."""
    if draft.turn_id != plan.turn_id or draft.session_revision != base_revision + 1:
        return [], [
            TurnRejection(
                code="turn_mismatch", message="the draft refers to a different turn or revision"
            )
        ]
    rejections: list[TurnRejection] = []
    if (
        draft.action_type != plan.action_type
        or draft.hint_level != plan.hint_level
        or set(draft.target_concept_ids) != set(plan.target_concept_ids)
    ):
        rejections.append(
            TurnRejection(
                code="plan_mismatch",
                message="the draft changed the planned action, hint level or target concepts",
            )
        )
    if draft.answer_revealed and not plan.reveal_allowed:
        rejections.append(
            TurnRejection(
                code="answer_disclosed",
                message="the draft marks the answer as revealed, which this turn does not allow",
            )
        )
    if plan.reveal_allowed and not draft.answer_revealed:
        rejections.append(
            TurnRejection(
                code="disclosure_not_marked",
                message="the planned explanation shows a completed step, so it must be marked",
            )
        )
    # The verifier's status is authoritative; a provider's own reading can never override it.
    if draft.step_assessment != plan.step_status:
        rejections.append(
            TurnRejection(
                code="provider_overrides_verifier",
                message="the draft's step assessment disagrees with the verifier",
            )
        )
    rejections.extend(_disclosures(plan, [draft.utterance]))

    actions, tool_rejections = validate_tool_actions(repo, session_id, draft.drawing_actions)
    rejections.extend(
        TurnRejection(code=rejection.code, message=rejection.message)
        for rejection in tool_rejections
    )
    if not tool_rejections:
        rejections.extend(_disclosures(plan, text_of_actions(actions)))

    allowed = citable_for_turn(context_citable_ids, plan)
    uncitable = [ref for ref in draft.evidence_ids if ref not in allowed]
    if uncitable:
        rejections.append(
            TurnRejection(
                code="uncitable_evidence",
                message=f"{len(uncitable)} cited ID(s) were not in the turn's context",
            )
        )
    missing = [ref for ref in plan.required_evidence_ids if ref not in draft.evidence_ids]
    if missing:
        rejections.append(
            TurnRejection(
                code="missing_grounding",
                message=f"the draft dropped {len(missing)} evidence ID(s) the plan requires",
            )
        )
    return ([], rejections) if rejections else (actions, [])
