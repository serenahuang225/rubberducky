"""Learner-scoped personal evidence links (support or contradiction for a hypothesis)."""

from datetime import datetime

from sqlalchemy import select

from app.db.models import EvidenceLinkRow
from app.db.repositories import ScopedRepository
from app.learner.pairing import new_id
from app.schemas import EvidenceLink, EvidencePolarity, Provenance


def link_evidence(
    repo: ScopedRepository,
    *,
    hypothesis_id: str,
    observation_id: str,
    polarity: EvidencePolarity,
    strength: float,
    rationale: str,
    now: datetime,
    provenance: Provenance = "submitted",
) -> EvidenceLink:
    """Record that an own observation supports or contradicts an own hypothesis.

    Both references are resolved inside the caller's scope first; the composite foreign
    keys reject a cross-learner link even if this check were bypassed.
    """
    repo.require_hypothesis(hypothesis_id)
    repo.require_observation(observation_id)
    link = EvidenceLink(
        id=new_id(),
        learner_id=repo.learner_id,
        hypothesis_id=hypothesis_id,
        observation_id=observation_id,
        polarity=polarity,
        strength=strength,
        rationale=rationale,
        provenance=provenance,
        created_at=now,
    )
    repo.db.add(EvidenceLinkRow(**link.model_dump()))
    repo.db.flush()
    return link


def links_for_hypothesis(
    repo: ScopedRepository, hypothesis_id: str, polarity: EvidencePolarity | None = None
) -> list[EvidenceLink]:
    repo.require_hypothesis(hypothesis_id)
    query = select(EvidenceLinkRow).where(
        EvidenceLinkRow.learner_id == repo.learner_id,
        EvidenceLinkRow.hypothesis_id == hypothesis_id,
    )
    if polarity is not None:
        query = query.where(EvidenceLinkRow.polarity == polarity)
    rows = repo.db.execute(query.order_by(EvidenceLinkRow.created_at, EvidenceLinkRow.id))
    return [EvidenceLink.model_validate(row) for row in rows.scalars()]


def supporting_evidence(repo: ScopedRepository, hypothesis_id: str) -> list[EvidenceLink]:
    return links_for_hypothesis(repo, hypothesis_id, "supports")


def contradicting_evidence(repo: ScopedRepository, hypothesis_id: str) -> list[EvidenceLink]:
    return links_for_hypothesis(repo, hypothesis_id, "contradicts")
