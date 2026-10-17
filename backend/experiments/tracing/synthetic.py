"""Seeded synthetic eligible interactions.

Outcomes follow a fixed pattern so a run is reproducible. They are not student responses,
and the pattern is not a claim about how people learn.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.tracing.contracts import TracingEvent
from experiments.tracing.windows import LearnerSplit, SequenceExample, split_learners

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SyntheticEvent:
    observation_id: str
    learner_id: str
    concept_id: str
    correct: int
    observed_at: datetime
    opportunity_key: str
    eligible: bool
    ineligible_reason: str | None = None


@dataclass(frozen=True)
class SyntheticCorpus:
    seed: int
    n_train: int
    n_heldout: int
    length: int
    events: tuple[SyntheticEvent, ...]
    split: LearnerSplit
    concept_ids: tuple[str, ...]
    prerequisites: dict[str, tuple[str, ...]]

    @property
    def train_ids(self) -> tuple[str, ...]:
        return self.split.train_ids

    @property
    def heldout_ids(self) -> tuple[str, ...]:
        return self.split.heldout_ids


def generate_synthetic_corpus(
    *,
    seed: int,
    n_train: int = 4,
    n_heldout: int = 2,
    n_concepts: int = 3,
    length: int = 6,
) -> SyntheticCorpus:
    """Assign learners to splits first, then emit each learner's own chronological events."""

    if n_train < 1 or n_heldout < 1 or n_concepts < 1 or length < 1:
        raise ValueError("synthetic corpus sizes must be positive")
    learner_ids = [f"learner.train.{index}" for index in range(n_train)]
    learner_ids.extend(f"learner.heldout.{index}" for index in range(n_heldout))
    split = split_learners(learner_ids, heldout_count=n_heldout, seed=seed)
    concept_ids = tuple(f"concept.c{index}" for index in range(n_concepts))
    prerequisites = {
        concept_ids[0]: (),
        **{concept_ids[index]: (concept_ids[index - 1],) for index in range(1, n_concepts)},
    }
    events: list[SyntheticEvent] = []
    clock = ORIGIN
    for learner_id in (*split.train_ids, *split.heldout_ids):
        for step in range(length):
            concept_id = concept_ids[step % n_concepts]
            correct = 0 if (step + len(learner_id)) % 3 == 0 else 1
            events.append(
                SyntheticEvent(
                    observation_id=f"obs.{learner_id}.{step}",
                    learner_id=learner_id,
                    concept_id=concept_id,
                    correct=correct,
                    observed_at=clock,
                    opportunity_key=f"{concept_id}|problem.{learner_id}.{step}",
                    eligible=True,
                )
            )
            clock += timedelta(minutes=1)
    heldout_learner = split.heldout_ids[0]
    first = next(event for event in events if event.learner_id == heldout_learner)
    events.append(
        SyntheticEvent(
            observation_id="obs.ineligible",
            learner_id=heldout_learner,
            concept_id=first.concept_id,
            correct=1,
            observed_at=clock,
            opportunity_key=f"{first.concept_id}|problem.assisted",
            eligible=False,
            ineligible_reason="assisted",
        )
    )
    clock += timedelta(minutes=1)
    events.append(
        SyntheticEvent(
            observation_id="obs.duplicate",
            learner_id=heldout_learner,
            concept_id=first.concept_id,
            correct=1 - first.correct,
            observed_at=clock,
            opportunity_key=first.opportunity_key,
            eligible=True,
        )
    )
    return SyntheticCorpus(
        seed=seed,
        n_train=n_train,
        n_heldout=n_heldout,
        length=length,
        events=tuple(events),
        split=split,
        concept_ids=concept_ids,
        prerequisites=prerequisites,
    )


def to_sequence_example(event: SyntheticEvent) -> SequenceExample:
    return SequenceExample(
        observation_id=event.observation_id,
        learner_id=event.learner_id,
        concept_id=event.concept_id,
        correct=event.correct,
        observed_at=event.observed_at,
        opportunity_key=event.opportunity_key,
        eligible=event.eligible,
    )


def to_tracing_event(event: SyntheticEvent) -> TracingEvent:
    payload: dict[str, object] = {
        "observation_id": event.observation_id,
        "learner_id": event.learner_id,
        "concept_id": event.concept_id,
        "correct": bool(event.correct),
        "source_type": "assessment",
        "source_id": f"assessment.{event.observation_id}",
        "assessment_id": f"assessment.{event.observation_id}",
        "assessment_kind": "practice_check",
        "problem_id": event.opportunity_key.split("|", 1)[1],
        "opportunity_key": event.opportunity_key,
        "eligible": event.eligible,
        "ineligible_reason": event.ineligible_reason,
        "provenance": "fictional_seed",
        "observed_at": event.observed_at,
    }
    if not event.eligible:
        payload["opportunity_key"] = None
    return TracingEvent.model_validate(payload)
