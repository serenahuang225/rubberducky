"""The learner's private memory view in plain language.

Every item says what is remembered, where it came from (each cited source explained, with an
excerpt while it still exists), how sure the system is, and why it matters for teaching. Items
also name the correction/deletion calls that apply to them, so a client does not need to know
the storage layout. Estimates are shown qualitatively because the hand-set parameters are
uncalibrated.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.models import (
    AssessmentRow,
    BKTCountedOpportunityRow,
    ConceptRow,
    EvidenceCorrectionRow,
    HintRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SessionRow,
    StepRow,
    TutorTurnRow,
)
from app.db.repositories import ScopedRepository
from app.learner.memory import active_session_context, episodic_notes, latest_estimates
from app.schemas import MasteryEstimate, MemoryEntry, MisconceptionHypothesis, Observation
from app.schemas.agency import (
    MAX_INSPECTION_ITEMS,
    CorrectionInfo,
    ItemAction,
    ItemState,
    MemoryInspection,
    MemoryItem,
    Qualitative,
    SourceExplanation,
    Uncertainty,
)
from app.tracing.presentation import readiness_band

MAX_EXPLAINED_SOURCES = 8
_EPISTEMIC = {
    "observed_work": "observed",
    "verified_assessment": "verified",
    "self_report": "self_report",
    "inference": "inference",
}
_BAND_TEXT = {
    "not_enough_evidence": "not enough independent evidence yet",
    "emerging": "just starting to show up",
    "developing": "developing",
    "strong_so_far": "looking strong so far",
}


def _qualitative(confidence: float) -> Qualitative:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.4:
        return "moderate"
    return "low"


def _clip(text: str, size: int) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"


def _fallback(source_id: str) -> SourceExplanation:
    return SourceExplanation(
        id=source_id,
        kind="unknown",
        label="No longer available: it was deleted or never recorded for you.",
        available=False,
    )


def explain_sources(repo: ScopedRepository, ids: Iterable[str]) -> dict[str, SourceExplanation]:
    """Explain each ID that belongs to this learner; anything else reads as unavailable."""
    wanted = list(dict.fromkeys(ids))
    found: dict[str, SourceExplanation] = {}
    if not wanted:
        return found
    db = repo.db
    learner = repo.learner_id

    def rows(model: Any) -> list[Any]:
        return list(
            db.execute(
                select(model).where(model.id.in_(wanted), model.learner_id == learner)
            ).scalars()
        )

    for step in rows(StepRow):
        found[step.id] = SourceExplanation(
            id=step.id,
            kind="step",
            label="A step you typed or confirmed",
            at=step.submitted_at,
            excerpt=_clip(step.content, 200),
        )
    for assessment in rows(AssessmentRow):
        found[assessment.id] = SourceExplanation(
            id=assessment.id,
            kind="assessment",
            label=(
                f"A check of a whole problem attempt ({assessment.kind.replace('_', ' ')}), "
                f"result: {assessment.outcome}"
            ),
            at=assessment.assessed_at,
        )
    for hint in rows(HintRow):
        found[hint.id] = SourceExplanation(
            id=hint.id,
            kind="hint",
            label=f"A tutor hint (level {hint.level})",
            at=hint.given_at,
            excerpt=_clip(hint.content, 200),
        )
    for observation in rows(ObservationRow):
        found[observation.id] = SourceExplanation(
            id=observation.id,
            kind="observation",
            label=f"A recorded observation ({observation.evidence_kind.replace('_', ' ')})",
            at=observation.observed_at,
        )
    for hypothesis in rows(MisconceptionHypothesisRow):
        found[hypothesis.id] = SourceExplanation(
            id=hypothesis.id,
            kind="hypothesis",
            label=f"A tentative guess: {hypothesis.label}",
            at=hypothesis.updated_at,
        )
    for entry in rows(MemoryEntryRow):
        found[entry.id] = SourceExplanation(
            id=entry.id,
            kind="memory_entry",
            label="A memory note",
            at=entry.created_at,
            excerpt=_clip(entry.content, 200),
        )
    for session in rows(SessionRow):
        found[session.id] = SourceExplanation(
            id=session.id,
            kind="session",
            label="A tutoring session",
            at=session.started_at,
        )
    for turn in rows(TutorTurnRow):
        found[turn.id] = SourceExplanation(
            id=turn.id, kind="turn", label="A tutor turn", at=turn.created_at
        )
    return {source_id: found.get(source_id, _fallback(source_id)) for source_id in wanted}


def _actions(base: str, record_id: str, *, correct: bool, delete: bool = True) -> list[ItemAction]:
    actions: list[ItemAction] = []
    if correct:
        actions.append(
            ItemAction(
                action="correct", method="POST", path=f"/memory/{base}/{record_id}/correction"
            )
        )
    if delete:
        actions.append(
            ItemAction(action="delete", method="DELETE", path=f"/memory/{base}/{record_id}")
        )
    return actions


def _concept_names(repo: ScopedRepository) -> dict[str, str]:
    return dict(repo.db.execute(select(ConceptRow.id, ConceptRow.name)).all())


def _evidence_summary(observation: Observation, concept: str | None) -> tuple[str, str, str]:
    """(title, summary, why_it_matters) for one observation."""
    topic = f" on {concept}" if concept else ""
    if observation.source_type == "check_in":
        return (
            "Check-in",
            "You told the tutor how you were doing at the start of a session.",
            "Used only to set this session's pace. It never lowers a mastery estimate.",
        )
    if observation.source_type == "help_request":
        return (
            "Help request",
            f"You asked for help{topic}. Asking for help is not treated as a wrong answer.",
            "Lets the tutor offer a smaller step. It does not count as independent evidence.",
        )
    help_note = " with help" if observation.assisted else ""
    if observation.correct is True:
        summary = f"Your work{topic} was checked and found correct{help_note}."
    elif observation.correct is False:
        summary = f"Your work{topic} was checked and found not correct{help_note}."
    else:
        summary = f"Your work{topic} was recorded but could not be judged right or wrong."
    why = (
        "Only unassisted, verified results feed the estimate; work done with help is kept "
        "as support but not counted as independent."
        if observation.correct is not None
        else "It is kept as a record but does not change any estimate."
    )
    return (f"Work{topic}".strip(), summary, why)


def _evidence_item(
    repo: ScopedRepository,
    observation: Observation,
    corrections: dict[str, EvidenceCorrectionRow],
    names: dict[str, str],
) -> MemoryItem:
    concept = names.get(observation.concept_id) if observation.concept_id else None
    title, summary, why = _evidence_summary(observation, concept)
    explanations = explain_sources(repo, [observation.source_id])
    sources = list(explanations.values())
    if observation.session_id is not None:
        sources.extend(explain_sources(repo, [observation.session_id]).values())
    correction = corrections.get(observation.id)
    info = None
    if correction is not None:
        info = CorrectionInfo(
            original="correct" if correction.original_correct else "not correct",
            current="correct" if correction.corrected_correct else "not correct",
            corrected_at=correction.corrected_at,
        )
    status = _EPISTEMIC[observation.evidence_kind]
    return MemoryItem(
        kind="evidence",
        id=observation.id,
        layer="raw_evidence",
        title=title,
        summary=summary,
        epistemic_status=status,  # type: ignore[arg-type]
        evidence_kind=observation.evidence_kind,
        state="corrected" if info is not None else "current",
        uncertainty=Uncertainty(
            qualitative=_qualitative(observation.confidence),
            confidence=observation.confidence,
            explanation=(
                "A mathematical check of typed or confirmed work; it does not show how you "
                "thought about it."
                if observation.evidence_kind in ("verified_assessment", "observed_work")
                else "Your own words, taken as you said them."
            ),
        ),
        why_it_matters=why,
        provenance=observation.provenance,
        origin="learner" if info is not None else "measured",
        sources=sources,
        correction=info,
        at=observation.observed_at,
        actions=_actions("evidence", observation.id, correct=observation.correct is not None),
    )


def _hypothesis_item(repo: ScopedRepository, hypothesis: MisconceptionHypothesis) -> MemoryItem:
    alternatives = "; ".join(hypothesis.alternatives)
    explanation = "A tentative guess from a few steps, not a diagnosis."
    if alternatives:
        explanation = _clip(f"{explanation} Other explanations: {alternatives}.", 240)
    state: ItemState = "retracted" if hypothesis.status == "retracted" else "current"
    return MemoryItem(
        kind="hypothesis",
        id=hypothesis.id,
        layer="derived_belief",
        title=hypothesis.label,
        summary=hypothesis.description,
        epistemic_status="inference",
        evidence_kind="inference",
        state=state,
        uncertainty=Uncertainty(
            qualitative=_qualitative(hypothesis.confidence),
            confidence=hypothesis.confidence,
            explanation=explanation,
        ),
        why_it_matters=(
            "Helps the tutor choose a smaller, more fitting hint. It is never used to grade you."
            if state == "current"
            else "Withdrawn because a source it relied on was corrected; it is no longer used."
        ),
        provenance=hypothesis.provenance,
        origin="system",
        sources=list(explain_sources(repo, hypothesis.source_ids).values()),
        at=hypothesis.updated_at,
        actions=_actions("hypotheses", hypothesis.id, correct=False),
    )


def _note_item(
    repo: ScopedRepository, entry: MemoryEntry, review_due: bool, kind: str
) -> MemoryItem:
    state: ItemState = "current"
    if entry.status == "corrected":
        state = "superseded"
    elif entry.status == "needs_review":
        state = "needs_review"
    elif entry.status == "expired":
        state = "expired"
    why = (
        "Lets the tutor recall earlier help when you come back; it only suggests, never grades."
        if kind == "note"
        else "Applies to this session only and is checked again next time."
    )
    if state == "needs_review" or (review_due and state == "current"):
        why = "Held back from teaching until you confirm or correct it."
    elif state == "superseded":
        why = "Replaced by your correction and no longer used."
    editable = entry.status in ("active", "needs_review")
    correction = None
    if entry.supersedes_id is not None:
        original = repo.db.execute(
            select(MemoryEntryRow.content).where(
                MemoryEntryRow.id == entry.supersedes_id,
                MemoryEntryRow.learner_id == repo.learner_id,
            )
        ).scalar_one_or_none()
        if original is not None:
            correction = CorrectionInfo(
                original=original[:500],
                current=entry.content[:500],
                corrected_at=entry.created_at,
            )
    return MemoryItem(
        kind=kind,  # type: ignore[arg-type]
        id=entry.id,
        layer="episodic_note" if kind == "note" else "session_context",
        title="Note" if kind == "note" else "This session only",
        summary=entry.content,
        epistemic_status=_EPISTEMIC[entry.evidence_kind],  # type: ignore[arg-type]
        evidence_kind=entry.evidence_kind,
        state=state,
        uncertainty=Uncertainty(
            qualitative=_qualitative(entry.confidence),
            confidence=entry.confidence,
            explanation=(
                "Your own words."
                if entry.evidence_kind == "self_report"
                else "Inferred from the cited sources, so it may be wrong."
            ),
        ),
        why_it_matters=why,
        provenance=entry.provenance,
        origin=entry.origin,
        sources=list(explain_sources(repo, entry.source_ids).values()),
        correction=correction,
        supersedes_id=entry.supersedes_id,
        at=entry.updated_at,
        actions=_actions("notes", entry.id, correct=editable),
    )


def _estimate_item(
    repo: ScopedRepository, estimate: MasteryEstimate, names: dict[str, str], counted: int
) -> MemoryItem:
    band = readiness_band(estimate.p_known, counted)
    concept = names.get(estimate.concept_id, estimate.concept_id)
    return MemoryItem(
        kind="estimate",
        id=estimate.id,
        layer="derived_estimate",
        title=f"Estimate for {concept}",
        summary=f"{concept}: {_BAND_TEXT[band]}.",
        epistemic_status="derived_estimate",
        state="current" if estimate.calibrated else "uncalibrated",
        uncertainty=Uncertainty(
            qualitative="low" if counted < 2 else "moderate",
            confidence=None,
            explanation=(
                f"Built from {counted} independent opportunit{'y' if counted == 1 else 'ies'} "
                "with hand-set, uncalibrated settings; it is not a score."
            ),
        ),
        why_it_matters=(
            "Guides how much support to offer. Fix it by correcting or deleting the evidence "
            "behind it; it is recomputed from what remains."
        ),
        provenance=estimate.provenance,
        origin="system",
        sources=list(
            explain_sources(repo, estimate.source_observation_ids[-MAX_EXPLAINED_SOURCES:]).values()
        ),
        at=estimate.computed_at,
        actions=[],
    )


def inspect_memory(
    repo: ScopedRepository,
    now: datetime,
    *,
    limit: int = 20,
    session_id: str | None = None,
) -> MemoryInspection:
    bounded = max(1, min(limit, MAX_INSPECTION_ITEMS))
    names = _concept_names(repo)
    current = repo.require_session(session_id).id if session_id is not None else None
    if current is None:
        current = repo.db.execute(
            select(SessionRow.id)
            .where(SessionRow.learner_id == repo.learner_id, SessionRow.status == "active")
            .order_by(SessionRow.started_at.desc(), SessionRow.id)
            .limit(1)
        ).scalar_one_or_none()
    items: list[MemoryItem] = [
        _note_item(repo, entry, False, "session_context")
        for entry in active_session_context(repo, current, now)[:bounded]
    ]
    items.extend(
        _note_item(repo, note.entry, note.review_due, "note")
        for note in episodic_notes(repo, now, bounded)
    )
    hypotheses = repo.db.execute(
        select(MisconceptionHypothesisRow)
        .where(MisconceptionHypothesisRow.learner_id == repo.learner_id)
        .order_by(MisconceptionHypothesisRow.updated_at.desc(), MisconceptionHypothesisRow.id)
        .limit(bounded)
    ).scalars()
    items.extend(
        _hypothesis_item(repo, MisconceptionHypothesis.model_validate(row)) for row in hypotheses
    )
    for estimate in latest_estimates(repo)[:bounded]:
        counted = repo.db.execute(
            select(BKTCountedOpportunityRow.id).where(
                BKTCountedOpportunityRow.learner_id == repo.learner_id,
                BKTCountedOpportunityRow.concept_id == estimate.concept_id,
                BKTCountedOpportunityRow.parameter_version == estimate.parameter_version,
            )
        ).all()
        items.append(_estimate_item(repo, estimate, names, len(counted)))
    observations = list(
        repo.db.execute(
            select(ObservationRow)
            .where(ObservationRow.learner_id == repo.learner_id)
            .order_by(ObservationRow.observed_at.desc(), ObservationRow.id)
            .limit(bounded)
        ).scalars()
    )
    corrections = {
        row.observation_id: row
        for row in repo.db.execute(
            select(EvidenceCorrectionRow).where(
                EvidenceCorrectionRow.learner_id == repo.learner_id,
                EvidenceCorrectionRow.observation_id.in_([o.id for o in observations]),
            )
        ).scalars()
    }
    items.extend(
        _evidence_item(repo, Observation.model_validate(row), corrections, names)
        for row in observations
    )
    return MemoryInspection(
        learner_id=repo.learner_id, generated_at=now, limit=bounded, items=items
    )
