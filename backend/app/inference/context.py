"""Bounded tutor context: what a provider may see for one turn, with its sources.

Selection is deterministic and model-free. It starts from the bounded graph context (the
curriculum neighborhood plus the learner's own support/contradiction evidence), then adds a
few recent observations from a fixed window, the current session's temporary context,
usable episodic notes, preferences, persona and derived estimates. Nothing outside those
bounds is loaded, so a lifetime transcript can never reach a provider by default.

The selection is then serialized and measured. While it exceeds the character or token
budget, free text is summarized away from the lowest-priority items first (IDs, polarity
and epistemic status stay), and then whole low-priority items are dropped. Dropped items
are counted in ``omitted`` and their IDs leave ``citable_ids``.
"""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.db.models import ConceptRow, ObservationRow
from app.db.repositories import ScopedRepository
from app.graph.context import _interleave_polarities, build_graph_context
from app.inference.tokens import DEFAULT_TOKEN_COUNTER, TokenCounter
from app.learner.memory import (
    active_session_context,
    latest_estimates,
    non_current_memory_ids,
    preferences,
    stale_session_context_count,
    usable_notes,
)
from app.schemas.context import (
    ContextBudget,
    ContextItem,
    ContextItemKind,
    ContextPayload,
    EpistemicStatus,
    OmissionCount,
    OmissionReason,
    Sufficiency,
    TutorContext,
)

# Lower numbers are kept longest. The target concept is never dropped.
_PRIORITY: dict[ContextItemKind, int] = {
    "target_concept": 0,
    "session_context": 1,
    "hypothesis": 2,
    "evidence": 3,
    "related_concept": 4,
    "persona": 5,
    "mastery_estimate": 6,
    "prerequisite_edge": 7,
    "recent_observation": 8,
    "episodic_note": 9,
    "preference": 10,
}
# Hypothesis facts that carry evidence-link IDs split by polarity.
_LINK_FACTS = ("supporting_link_ids", "contradicting_link_ids")
_KEEP_TEXT: frozenset[ContextItemKind] = frozenset({"target_concept", "session_context"})
_EVIDENCE_KINDS: frozenset[ContextItemKind] = frozenset(
    {"hypothesis", "evidence", "recent_observation", "mastery_estimate"}
)
_STATUS_FOR_KIND: dict[str, EpistemicStatus] = {
    "observed_work": "observed",
    "verified_assessment": "verified",
    "self_report": "self_report",
    "inference": "inference",
}


def _status(evidence_kind: str) -> EpistemicStatus:
    return _STATUS_FOR_KIND[evidence_kind]


@dataclass
class _Candidate:
    priority: int
    sequence: int
    item: ContextItem


class _Selection:
    def __init__(self) -> None:
        self.candidates: list[_Candidate] = []
        self.omitted: Counter[tuple[ContextItemKind, OmissionReason]] = Counter()

    def add(self, item: ContextItem) -> None:
        self.candidates.append(_Candidate(_PRIORITY[item.kind], len(self.candidates), item))

    def omit(self, kind: ContextItemKind, reason: OmissionReason, count: int) -> None:
        if count > 0:
            self.omitted[(kind, reason)] += count


def _select(
    repo: ScopedRepository,
    concept_id: str,
    session_id: str | None,
    now: datetime,
    budget: ContextBudget,
) -> tuple[_Selection, list[str]]:
    selection = _Selection()
    graph = build_graph_context(repo, concept_id, now, budget.graph)
    concept = repo.db.get(ConceptRow, concept_id)
    for node in graph.nodes:
        selection.add(
            ContextItem(
                ref=node.concept_id,
                kind="target_concept" if node.relation == "target" else "related_concept",
                status="curriculum",
                concept_id=node.concept_id,
                facts={"name": node.name, "relation": node.relation, "hops": node.hops},
                text=concept.description
                if node.relation == "target" and concept is not None
                else None,
            )
        )
    for edge in graph.curriculum_edges:
        selection.add(
            ContextItem(
                ref=edge.edge_id,
                kind="prerequisite_edge",
                status="curriculum",
                facts={"prerequisite_id": edge.prerequisite_id, "concept_id": edge.concept_id},
            )
        )
    selection.omit("related_concept", "selection_bound", graph.omitted.nodes)

    for hypothesis in graph.hypotheses:
        selection.add(
            ContextItem(
                ref=hypothesis.hypothesis_id,
                kind="hypothesis",
                status="inference",
                concept_id=hypothesis.concept_id,
                facts={
                    "label": hypothesis.label,
                    "hypothesis_status": hypothesis.status,
                    "confidence": round(hypothesis.confidence, 3),
                    "alternatives": hypothesis.alternatives,
                    "supporting_link_ids": hypothesis.supporting_link_ids,
                    "contradicting_link_ids": hypothesis.contradicting_link_ids,
                },
            )
        )
    selection.omit("hypothesis", "selection_bound", graph.omitted.hypotheses)

    for evidence in _interleave_polarities(list(graph.evidence)):
        selection.add(
            ContextItem(
                ref=evidence.link_id,
                kind="evidence",
                status=_status(evidence.evidence_kind),
                polarity=evidence.polarity,
                hypothesis_id=evidence.hypothesis_id,
                concept_id=evidence.concept_id,
                at=evidence.observed_at,
                source_ids=list(dict.fromkeys([evidence.observation_id, evidence.source_id])),
                facts={
                    "correct": evidence.correct,
                    "assisted": evidence.assisted,
                    "strength": round(evidence.strength, 3),
                    "confidence": round(evidence.confidence, 3),
                    "source_type": evidence.source_type,
                    "provenance": evidence.provenance,
                },
                text=evidence.rationale,
            )
        )
    selection.omit("evidence", "selection_bound", graph.omitted.evidence)

    node_ids = [node.concept_id for node in graph.nodes]
    linked = {evidence.observation_id for evidence in graph.evidence}
    cutoff = now - timedelta(days=budget.recent_window_days)
    in_window = (
        select(ObservationRow)
        .where(
            ObservationRow.learner_id == repo.learner_id,
            ObservationRow.concept_id.in_(node_ids),
            ObservationRow.observed_at <= now,
            ObservationRow.observed_at >= cutoff,
        )
        .order_by(ObservationRow.observed_at.desc(), ObservationRow.id)
    )
    recent = [
        row
        for row in repo.db.execute(
            in_window.limit(budget.max_recent_observations + len(linked))
        ).scalars()
        if row.id not in linked
    ][: budget.max_recent_observations]
    window_total = repo.db.execute(
        select(func.count()).select_from(in_window.subquery())
    ).scalar_one()
    linked_in_window = repo.db.execute(
        select(func.count()).select_from(
            in_window.where(ObservationRow.id.in_(linked)).subquery()
        )
    ).scalar_one()
    older = repo.db.execute(
        select(func.count()).where(
            ObservationRow.learner_id == repo.learner_id,
            ObservationRow.concept_id.in_(node_ids),
            ObservationRow.observed_at < cutoff,
        )
    ).scalar_one()
    for row in recent:
        selection.add(
            ContextItem(
                ref=row.id,
                kind="recent_observation",
                status=_status(row.evidence_kind),
                concept_id=row.concept_id,
                at=row.observed_at,
                source_ids=[row.source_id],
                facts={
                    "correct": row.correct,
                    "assisted": row.assisted,
                    "confidence": round(row.confidence, 3),
                    "source_type": row.source_type,
                    "latency_ms": row.latency_ms,
                    "provenance": row.provenance,
                },
            )
        )
    selection.omit(
        "recent_observation", "selection_bound", window_total - linked_in_window - len(recent)
    )
    selection.omit("recent_observation", "outside_window", older)

    for estimate in latest_estimates(repo, node_ids):
        selection.add(
            ContextItem(
                ref=estimate.id,
                kind="mastery_estimate",
                status="derived_estimate",
                concept_id=estimate.concept_id,
                at=estimate.computed_at,
                source_ids=estimate.source_observation_ids,
                facts={
                    "p_known": round(estimate.p_known, 3),
                    "calibrated": estimate.calibrated,
                    "algorithm_version": estimate.algorithm_version,
                    "parameter_version": estimate.parameter_version,
                },
            )
        )

    gaps: list[str] = []
    active_context = active_session_context(repo, session_id, now) if session_id else []
    if session_id is None:
        gaps.append("no_session")
    elif repo.require_session(session_id).status != "active":
        gaps.append("session_not_active")
    for entry in active_context[: budget.max_session_context]:
        selection.add(
            ContextItem(
                ref=entry.id,
                kind="session_context",
                status=_status(entry.evidence_kind),
                at=entry.created_at,
                source_ids=entry.source_ids,
                facts={
                    "scope": "this_session_only",
                    "confidence": round(entry.confidence, 3),
                    "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
                },
                text=entry.content,
            )
        )
    selection.omit(
        "session_context",
        "selection_bound",
        len(active_context) - min(len(active_context), budget.max_session_context),
    )
    stale = stale_session_context_count(repo, session_id, now)
    selection.omit("session_context", "not_current_session", stale)
    if stale and not active_context:
        gaps.append("session_context_needs_recheck")

    notes, held_back = usable_notes(repo, now)
    for note in notes[: budget.max_notes]:
        selection.add(
            ContextItem(
                ref=note.id,
                kind="episodic_note",
                status=_status(note.evidence_kind),
                at=note.created_at,
                source_ids=note.source_ids,
                facts={
                    "confidence": round(note.confidence, 3),
                    "origin": note.origin,
                    "review_at": note.review_at.isoformat() if note.review_at else None,
                },
                text=note.content,
            )
        )
    selection.omit("episodic_note", "selection_bound", len(notes) - len(notes[: budget.max_notes]))
    selection.omit("episodic_note", "review_due", held_back)

    persona = repo.tutor_configuration()
    if persona is not None:
        selection.add(
            ContextItem(
                ref=persona.id,
                kind="persona",
                status="learner_setting",
                at=persona.last_changed_at,
                facts={
                    "appearance": persona.appearance,
                    "personality": persona.personality,
                    "comfort_override": persona.comfort_override,
                },
            )
        )
    own_preferences = preferences(repo)
    for preference in own_preferences[: budget.max_preferences]:
        selection.add(
            ContextItem(
                ref=preference.id,
                kind="preference",
                status="learner_setting",
                at=preference.updated_at,
                facts={"key": preference.key, "value": preference.value},
            )
        )
    selection.omit(
        "preference",
        "selection_bound",
        len(own_preferences) - min(len(own_preferences), budget.max_preferences),
    )
    return selection, gaps


def _citable(items: list[ContextItem], non_current: frozenset[str] = frozenset()) -> list[str]:
    ids: dict[str, None] = {}
    for item in items:
        ids[item.ref] = None
        for source_id in item.source_ids:
            if source_id not in non_current:
                ids[source_id] = None
        if item.hypothesis_id is not None:
            ids[item.hypothesis_id] = None
        for key in _LINK_FACTS:
            linked = item.facts.get(key)
            if isinstance(linked, list):
                ids.update(dict.fromkeys(linked))
    return list(ids)


def _payload(
    concept_id: str,
    session_id: str | None,
    kept: list[_Candidate],
    selection: _Selection,
    budget_dropped: Counter[ContextItemKind],
    gaps: list[str],
    insufficient: bool,
) -> ContextPayload:
    all_gaps = list(gaps)
    kinds = {c.item.kind for c in selection.candidates}
    if not kinds & _EVIDENCE_KINDS:
        all_gaps.append("no_prior_evidence_for_concept")
    if any(budget_dropped[k] for k in (*_EVIDENCE_KINDS, "session_context")):
        all_gaps.append("evidence_omitted_by_budget")
    if insufficient:
        all_gaps.append("budget_too_small")
    sufficiency: Sufficiency = "sufficient"
    if insufficient:
        sufficiency = "insufficient"
    elif {"no_prior_evidence_for_concept", "evidence_omitted_by_budget"} & set(all_gaps):
        sufficiency = "limited"
    omitted = Counter(selection.omitted)
    for kind, count in budget_dropped.items():
        omitted[(kind, "budget")] += count
    return ContextPayload(
        target_concept_id=concept_id,
        session_id=session_id,
        sufficiency=sufficiency,
        gaps=all_gaps,
        session_context_recheck="session_context_needs_recheck" in gaps,
        items=[c.item for c in kept],
        omitted=[
            OmissionCount(kind=kind, reason=reason, count=count)
            for (kind, reason), count in sorted(omitted.items())
            if count > 0
        ],
    )


def serialize_payload(payload: ContextPayload) -> str:
    """Canonical compact JSON. Empty/default item fields are left out to save budget.

    Omissions are rendered as a ``{"kind/reason": count}`` mapping for the same reason.
    """
    data = payload.model_dump(mode="json", exclude_none=True)
    data["items"] = [
        {k: v for k, v in item.items() if v not in ([], {}) and not (k == "summarized" and not v)}
        for item in data["items"]
    ]
    data["omitted"] = {f"{o['kind']}/{o['reason']}": o["count"] for o in data["omitted"]}
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def build_tutor_context(
    repo: ScopedRepository,
    concept_id: str,
    now: datetime,
    *,
    session_id: str | None = None,
    budget: ContextBudget | None = None,
    counter: TokenCounter = DEFAULT_TOKEN_COUNTER,
    max_chars: int | None = None,
    max_tokens: int | None = None,
) -> TutorContext:
    """Select, then fit to ``budget`` (optionally tightened by ``max_chars``/``max_tokens``).

    Raises ``UnknownConceptError`` for an unknown concept and ``NotInScopeError`` for a
    session that is not the learner's own.
    """
    budget = budget or ContextBudget()
    if session_id is not None:
        repo.require_session(session_id)
    char_limit = budget.max_serialized_chars
    token_limit = budget.max_context_tokens
    if max_chars is not None:
        char_limit = max(0, min(char_limit, max_chars))
    if max_tokens is not None:
        token_limit = max(0, min(token_limit, max_tokens))

    selection, gaps = _select(repo, concept_id, session_id, now, budget)
    kept = sorted(selection.candidates, key=lambda c: (c.priority, c.sequence))
    dropped: list[_Candidate] = []
    budget_dropped: Counter[ContextItemKind] = Counter()

    def render(insufficient: bool = False) -> tuple[ContextPayload, str, int]:
        payload = _payload(
            concept_id, session_id, kept, selection, budget_dropped, gaps, insufficient
        )
        text = serialize_payload(payload)
        return payload, text, counter.count(text)

    def fits(text: str, tokens: int) -> bool:
        return len(text) <= char_limit and tokens <= token_limit

    def summarize(candidate: _Candidate) -> None:
        candidate.item = candidate.item.model_copy(update={"text": None, "summarized": True})

    payload, text, tokens = render()
    # Phase 1: summarize free text (rationales, notes) away, lowest priority first. IDs,
    # polarity and epistemic status remain. The target and session context keep their text.
    for candidate in reversed(kept):
        if fits(text, tokens):
            break
        if candidate.item.text is not None and candidate.item.kind not in _KEEP_TEXT:
            summarize(candidate)
            payload, text, tokens = render()
    # Phase 2: drop whole items, lowest priority first. Session context and the target are
    # summarized before they could be dropped; the target concept is never dropped.
    while not fits(text, tokens):
        last = kept[-1]
        if last.item.text is not None:
            summarize(last)
        elif last.item.kind == "target_concept":
            break
        else:
            kept.pop()
            dropped.append(last)
            budget_dropped[last.item.kind] += 1
        payload, text, tokens = render()
    insufficient = not fits(text, tokens)
    if insufficient:
        payload, text, tokens = render(insufficient=True)

    non_current = non_current_memory_ids(repo)
    citable = _citable([c.item for c in kept], non_current)
    citable_set = set(citable)
    omitted_ids = [
        i for i in _citable([c.item for c in dropped], non_current) if i not in citable_set
    ]
    return TutorContext(
        learner_id=repo.learner_id,
        generated_at=now,
        budget=budget,
        effective_max_chars=char_limit,
        effective_max_tokens=token_limit,
        payload=payload,
        serialized=text,
        serialized_chars=len(text),
        serialized_bytes=len(text.encode("utf-8")),
        token_count=tokens,
        token_counter=counter.name,
        within_budget=fits(text, tokens),
        citable_ids=citable,
        budget_omitted_ids=omitted_ids,
    )


def uncitable_ids(context: TutorContext, cited: list[str]) -> list[str]:
    """IDs a provider cited that were not in the context it was given."""
    allowed = set(context.citable_ids)
    return [source_id for source_id in cited if source_id not in allowed]


def render_context_text(context: TutorContext) -> str:
    """Human-readable view that keeps every ID, polarity, status and measurement."""
    p = context.payload
    lines = [
        f"tutor context for {p.target_concept_id} (learner {context.learner_id}, "
        f"session {p.session_id})",
        f"selector={context.selector} generated_at={context.generated_at.isoformat()}",
        f"sufficiency={p.sufficiency} gaps={p.gaps} recheck_session_context="
        f"{p.session_context_recheck}",
        f"serialized: {context.serialized_chars} chars / {context.serialized_bytes} bytes, "
        f"{context.token_count} tokens ({context.token_counter}); limits "
        f"{context.effective_max_chars} chars / {context.effective_max_tokens} tokens; "
        f"within_budget={context.within_budget}",
        "items (priority order):",
    ]
    for item in p.items:
        polarity = f" {item.polarity.upper()} {item.hypothesis_id}" if item.polarity else ""
        summarized = " [summarized]" if item.summarized else ""
        lines.append(
            f"  {item.kind} {item.ref} status={item.status}{polarity}{summarized} "
            f"sources={item.source_ids} facts={item.facts}"
            + (f" - {item.text}" if item.text else "")
        )
    lines.append("omitted:")
    lines.extend(f"  {o.kind}: {o.count} ({o.reason})" for o in p.omitted)
    lines.append("source ids a tutor turn may cite:")
    lines.extend(f"  {source_id}" for source_id in context.citable_ids)
    if context.budget_omitted_ids:
        lines.append("ids removed by the size budget (not citable):")
        lines.extend(f"  {source_id}" for source_id in context.budget_omitted_ids)
    return "\n".join(lines)
