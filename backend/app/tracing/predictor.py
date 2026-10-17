"""Common statistical predictor interface and the NumPy BKT predictor behind it.

A predictor instance belongs to exactly one learner. The contract is:

1. ``predict_before_observation(concept_id)`` returns the probability of the next
   independent response being correct, computed only from already-observed events.
2. ``observe(event)`` applies one raw event. It always predicts first, so a response can
   never inform its own prediction, and it reports events that change nothing.
3. ``reset()`` returns to the initial state; ``save()``/``load()`` round-trip that state with
   version metadata, refusing a snapshot made with other parameters or algorithm versions.

A future GRU can implement the same protocol with its own snapshot type. It would report
``latent_knowledge=None`` and ``has_latent_state=False`` because a neural next-response
probability is not a latent-knowledge estimate.
"""

from typing import Protocol

from app.schemas import ContractModel
from app.tracing import bkt
from app.tracing.contracts import (
    ALGORITHM,
    ALGORITHM_VERSION,
    DEFAULT_PARAMETERS,
    ELIGIBILITY_VERSION,
    BKTParameters,
    BKTSnapshot,
    ConceptState,
    PredictorMetadata,
    ResponsePrediction,
    TracingEvent,
    TracingUpdate,
)


class SnapshotMismatchError(ValueError):
    """A snapshot does not belong to this predictor's learner, algorithm or parameters."""


class StatisticalPredictor[SnapshotT: ContractModel](Protocol):
    learner_id: str

    def metadata(self) -> PredictorMetadata: ...

    def predict_before_observation(self, concept_id: str) -> ResponsePrediction: ...

    def observe(self, event: TracingEvent) -> TracingUpdate: ...

    def reset(self) -> None: ...

    def save(self) -> SnapshotT: ...

    def load(self, snapshot: SnapshotT) -> None: ...


class BKTPredictor:
    """Per-concept BKT over the independent opportunity stream of one learner."""

    def __init__(self, learner_id: str, parameters: BKTParameters = DEFAULT_PARAMETERS) -> None:
        self.learner_id = learner_id
        self.parameters = parameters
        self.reset()

    def reset(self) -> None:
        self._p_known: dict[str, float] = {}
        self._opportunities: dict[str, list[str]] = {}
        self._sources: dict[str, list[str]] = {}
        self._observed: list[str] = []
        self._observed_set: set[str] = set()

    def metadata(self) -> PredictorMetadata:
        return PredictorMetadata(
            algorithm=ALGORITHM,
            algorithm_version=ALGORITHM_VERSION,
            eligibility_version=ELIGIBILITY_VERSION,
            parameter_version=self.parameters.parameter_version,
            has_latent_state=True,
            calibrated=self.parameters.calibrated,
        )

    def p_known(self, concept_id: str) -> float:
        return self._p_known.get(concept_id, self.parameters.p_init)

    def counted_opportunities(self, concept_id: str) -> list[str]:
        return list(self._opportunities.get(concept_id, []))

    def source_observation_ids(self, concept_id: str) -> list[str]:
        return list(self._sources.get(concept_id, []))

    def concepts(self) -> list[str]:
        return sorted(self._p_known)

    def predict_before_observation(self, concept_id: str) -> ResponsePrediction:
        p_known = self.p_known(concept_id)
        return ResponsePrediction(
            concept_id=concept_id,
            p_correct=bkt.predict_correct(p_known, self.parameters.p_guess, self.parameters.p_slip),
            latent_knowledge=p_known,
            algorithm=ALGORITHM,
            algorithm_version=ALGORITHM_VERSION,
            parameter_version=self.parameters.parameter_version,
            calibrated=self.parameters.calibrated,
            opportunities_counted=len(self._opportunities.get(concept_id, [])),
        )

    def _no_update(self, event: TracingEvent, status: str, reason: str | None) -> TracingUpdate:
        return TracingUpdate.model_validate(
            {
                "observation_id": event.observation_id,
                "concept_id": event.concept_id,
                "opportunity_key": event.opportunity_key,
                "status": status,
                "reason": reason,
                "observed_correct": event.correct,
            }
        )

    def observe(self, event: TracingEvent) -> TracingUpdate:
        if event.learner_id != self.learner_id:
            raise SnapshotMismatchError("event belongs to a different learner's history")
        if event.observation_id in self._observed_set:
            return self._no_update(event, "already_observed", "observation already applied")
        if not event.eligible:
            return self._no_update(event, "ineligible", event.ineligible_reason)
        if event.concept_id is None or event.correct is None or event.opportunity_key is None:
            raise ValueError("eligible event lacks concept, correctness or opportunity")
        concept_id = event.concept_id
        if event.opportunity_key in self._opportunities.get(concept_id, []):
            return self._no_update(
                event, "duplicate_opportunity", "opportunity already counted for this concept"
            )

        prediction = self.predict_before_observation(concept_id)
        p_before = self.p_known(concept_id)
        result = bkt.posterior(
            p_before, event.correct, self.parameters.p_guess, self.parameters.p_slip
        )
        self._observed.append(event.observation_id)
        self._observed_set.add(event.observation_id)
        if isinstance(result, bkt.ImpossibleObservation):
            update = self._no_update(event, "impossible_observation", result.detail)
            return update.model_copy(update={"prediction": prediction})

        p_after = bkt.learn_transition(result, self.parameters.p_learn)
        self._p_known[concept_id] = p_after
        self._opportunities.setdefault(concept_id, []).append(event.opportunity_key)
        self._sources.setdefault(concept_id, []).append(event.observation_id)
        return TracingUpdate(
            observation_id=event.observation_id,
            concept_id=concept_id,
            opportunity_key=event.opportunity_key,
            status="counted",
            sequence=len(self._opportunities[concept_id]),
            prediction=prediction,
            observed_correct=event.correct,
            p_known_posterior=result,
            p_known_after=p_after,
        )

    def save(self) -> BKTSnapshot:
        return BKTSnapshot(
            metadata=self.metadata(),
            learner_id=self.learner_id,
            parameters=self.parameters,
            concepts=[
                ConceptState(
                    concept_id=concept_id,
                    p_known=self._p_known[concept_id],
                    opportunity_keys=self.counted_opportunities(concept_id),
                    observation_ids=self.source_observation_ids(concept_id),
                )
                for concept_id in self.concepts()
            ],
            observed_ids=list(self._observed),
        )

    def load(self, snapshot: BKTSnapshot) -> None:
        if snapshot.learner_id != self.learner_id:
            raise SnapshotMismatchError("snapshot belongs to a different learner")
        if snapshot.metadata != self.metadata():
            raise SnapshotMismatchError(
                "snapshot algorithm, eligibility or parameter version differs; replay raw "
                "evidence instead of reusing an old posterior"
            )
        if snapshot.parameters != self.parameters:
            raise SnapshotMismatchError("snapshot parameter values differ from this predictor")
        self.reset()
        for state in snapshot.concepts:
            self._p_known[state.concept_id] = state.p_known
            self._opportunities[state.concept_id] = list(state.opportunity_keys)
            self._sources[state.concept_id] = list(state.observation_ids)
        self._observed = list(snapshot.observed_ids)
        self._observed_set = set(self._observed)

    @classmethod
    def from_snapshot(cls, snapshot: BKTSnapshot) -> "BKTPredictor":
        predictor = cls(snapshot.learner_id, snapshot.parameters)
        predictor.load(snapshot)
        return predictor
