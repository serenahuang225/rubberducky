"""Fictional fixtures for memory-layer and bounded-context tests (direct, scoped writes)."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.db.models import (
    EvidenceLinkRow,
    LearnerRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SessionRow,
)
from app.db.repositories import ScopedRepository
from app.learner.pairing import LearnerScope
from app.schemas import EvidenceLink, Learner, MisconceptionHypothesis, Observation, Session

DISTRIBUTION = "concept.distribution"


def scoped(db: DbSession, learner_id: str) -> ScopedRepository:
    return ScopedRepository(db, LearnerScope(learner_id=learner_id, credential_id="test"))


def add_learner(db: DbSession, learner_id: str, now: datetime) -> None:
    learner = Learner(
        id=learner_id,
        display_name=f"{learner_id} (fictional test learner)",
        is_fictional=True,
        provenance="submitted",
        created_at=now,
    )
    db.add(LearnerRow(**learner.model_dump()))
    db.flush()


def add_session(
    db: DbSession, learner_id: str, session_id: str, started_at: datetime, status: str = "ended"
) -> None:
    session = Session(
        id=session_id,
        learner_id=learner_id,
        status=status,  # type: ignore[arg-type]
        provenance="submitted",
        started_at=started_at,
        ended_at=None if status == "active" else started_at + timedelta(minutes=30),
    )
    db.add(SessionRow(**session.model_dump()))
    db.flush()


def add_observation(
    db: DbSession,
    learner_id: str,
    session_id: str | None,
    observation_id: str,
    observed_at: datetime,
    **overrides: Any,
) -> None:
    values: dict[str, Any] = {
        "id": observation_id,
        "learner_id": learner_id,
        "session_id": session_id,
        "source_type": "step",
        "source_id": f"src-{observation_id}",
        "evidence_kind": "observed_work",
        "concept_id": DISTRIBUTION,
        "correct": True,
        "confidence": 0.8,
        "assisted": False,
        "provenance": "submitted",
        "observed_at": observed_at,
        "recorded_at": observed_at,
    }
    values.update(overrides)
    db.add(ObservationRow(**Observation(**values).model_dump()))
    db.flush()


def add_hypothesis(
    db: DbSession, learner_id: str, hypothesis_id: str, at: datetime, source_id: str
) -> None:
    hypothesis = MisconceptionHypothesis(
        id=hypothesis_id,
        learner_id=learner_id,
        concept_id=DISTRIBUTION,
        label="Partial distribution",
        description="Multiplies only the first term inside parentheses.",
        confidence=0.5,
        alternatives=["Copying slip"],
        source_ids=[source_id],
        provenance="submitted",
        created_at=at,
        updated_at=at,
    )
    db.add(MisconceptionHypothesisRow(**hypothesis.model_dump()))
    db.flush()


def add_link(
    db: DbSession,
    learner_id: str,
    link_id: str,
    hypothesis_id: str,
    observation_id: str,
    polarity: str,
    at: datetime,
    rationale: str,
) -> None:
    link = EvidenceLink(
        id=link_id,
        learner_id=learner_id,
        hypothesis_id=hypothesis_id,
        observation_id=observation_id,
        polarity=polarity,  # type: ignore[arg-type]
        strength=0.5,
        rationale=rationale,
        provenance="submitted",
        created_at=at,
    )
    db.add(EvidenceLinkRow(**link.model_dump()))
    db.flush()


def overfull_history(
    db: DbSession, learner_id: str, now: datetime, days: int = 400
) -> dict[str, Any]:
    """One observation per day for ``days`` days, every 5th linked to a hypothesis.

    Linked even days support the partial-distribution hypothesis and odd days contradict it, so a
    lifetime transcript would be hundreds of records; the context must stay bounded.
    """
    add_learner(db, learner_id, now - timedelta(days=days + 1))
    session_id = f"{learner_id}-history"
    add_session(db, learner_id, session_id, now - timedelta(days=days + 1))
    hypothesis_id = f"{learner_id}-hyp"
    observation_ids = []
    for day in range(days):
        observation_id = f"{learner_id}-obs-{day:03d}"
        add_observation(
            db,
            learner_id,
            session_id,
            observation_id,
            now - timedelta(days=day, hours=1),
            correct=day % 2 == 1,
        )
        observation_ids.append(observation_id)
    add_hypothesis(db, learner_id, hypothesis_id, now - timedelta(days=1), observation_ids[0])
    links = []
    for day in range(0, days, 5):
        polarity = "supports" if day % 2 == 0 else "contradicts"
        link_id = f"{learner_id}-link-{day:03d}"
        add_link(
            db,
            learner_id,
            link_id,
            hypothesis_id,
            observation_ids[day],
            polarity,
            now - timedelta(days=day),
            f"RATIONALE-{day:03d} {'left the 3 alone' if polarity == 'supports' else 'did both'}",
        )
        links.append((link_id, polarity, day))
    return {
        "session_id": session_id,
        "hypothesis_id": hypothesis_id,
        "observation_ids": observation_ids,
        "links": links,
    }
