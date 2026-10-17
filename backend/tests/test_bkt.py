"""Hand-calculated BKT arithmetic, parameter boundaries and the common predictor interface.

Expected values below are worked by hand from the BKT formulas, not produced by the code:
p=.2, T=.1, g=.25, s=.1
  P(correct)            = .2(.9) + .8(.25)          = .38
  P(known | correct)    = .18 / .38                 = 9/19
  next after correct    = 9/19 + (10/19)(.1)        = 10/19
  P(known | incorrect)  = .02 / (.02 + .8(.75))     = 1/31
  next after incorrect  = 1/31 + (30/31)(.1)        = 4/31
"""

import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.tracing import bkt
from app.tracing.contracts import (
    DEFAULT_PARAMETERS,
    PREDICTION_TARGET,
    BKTParameters,
    TracingEvent,
)
from app.tracing.predictor import BKTPredictor, SnapshotMismatchError

TOL = 1e-12
P, T, G, S = 0.2, 0.1, 0.25, 0.1
LEARNER = "learner-1"
CONCEPT = "concept.linear_equations"


def close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= TOL


def event(
    observation_id: str,
    correct: bool | None,
    problem: str = "problem.a",
    *,
    eligible: bool = True,
    learner: str = LEARNER,
) -> TracingEvent:
    return TracingEvent.model_validate(
        {
            "observation_id": observation_id,
            "learner_id": learner,
            "concept_id": CONCEPT,
            "correct": correct,
            "source_type": "assessment",
            "source_id": f"assessment-{observation_id}",
            "assessment_id": f"assessment-{observation_id}",
            "assessment_kind": "practice_check",
            "problem_id": problem,
            "opportunity_key": f"{CONCEPT}|{problem}" if eligible else None,
            "eligible": eligible,
            "ineligible_reason": None if eligible else "assisted",
            "provenance": "submitted",
            "observed_at": datetime(2026, 10, 1, tzinfo=UTC),
        }
    )


def test_hand_calculated_fixture() -> None:
    assert close(bkt.predict_correct(P, G, S), 0.38)
    correct_post = bkt.posterior_if_correct(P, G, S)
    incorrect_post = bkt.posterior_if_incorrect(P, G, S)
    assert isinstance(correct_post, float) and isinstance(incorrect_post, float)
    assert close(correct_post, 9 / 19)
    assert close(bkt.learn_transition(correct_post, T), 10 / 19)
    assert close(incorrect_post, 1 / 31)
    assert close(bkt.learn_transition(incorrect_post, T), 4 / 31)


def test_latent_knowledge_and_predicted_correctness_are_different_quantities() -> None:
    predictor = BKTPredictor(LEARNER, DEFAULT_PARAMETERS)
    prediction = predictor.predict_before_observation(CONCEPT)
    assert prediction.target == PREDICTION_TARGET == "next_independent_response_correct"
    assert close(prediction.latent_knowledge or -1, 0.2)
    assert close(prediction.p_correct, 0.38)
    assert prediction.calibrated is False
    assert predictor.metadata().has_latent_state is True


@pytest.mark.parametrize(
    ("p", "correct", "g", "s", "posterior"),
    [
        (0.0, True, 0.25, 0.1, 0.0),  # never known: a correct answer is a guess
        (1.0, True, 0.25, 0.1, 1.0),
        (1.0, False, 0.25, 0.1, 1.0),  # known learner who slipped stays known
        (0.0, False, 0.25, 0.1, 0.0),
        (0.2, True, 0.0, 0.1, 1.0),  # no guessing: correct implies known
        (0.2, False, 0.25, 0.0, 0.0),  # no slipping: incorrect implies unknown
        (0.2, True, 1.0, 0.0, 0.2),  # everyone answers correctly: no information
    ],
)
def test_endpoint_posteriors_are_finite(
    p: float, correct: bool, g: float, s: float, posterior: float
) -> None:
    result = bkt.posterior(p, correct, g, s)
    assert isinstance(result, float) and math.isfinite(result)
    assert close(result, posterior)


@pytest.mark.parametrize(
    ("posterior", "t", "expected"),
    [(0.3, 0.0, 0.3), (0.3, 1.0, 1.0), (1.0, 0.4, 1.0), (0.0, 0.4, 0.4)],
)
def test_transition_endpoints(posterior: float, t: float, expected: float) -> None:
    assert close(bkt.learn_transition(posterior, t), expected)


@pytest.mark.parametrize(
    ("p", "correct", "g", "s"),
    [(0.0, True, 0.0, 0.1), (1.0, False, 0.25, 0.0), (1.0, True, 0.2, 1.0), (0.0, False, 1.0, 0.1)],
)
def test_impossible_observation_is_typed_not_nan(
    p: float, correct: bool, g: float, s: float
) -> None:
    result = bkt.posterior(p, correct, g, s)
    assert isinstance(result, bkt.ImpossibleObservation)
    assert result.reason == "zero_likelihood"
    assert result.observed_correct is correct


@pytest.mark.parametrize("bad", [-0.01, 1.01, math.nan, math.inf, -math.inf, True, "0.5", None])
def test_functions_reject_invalid_probabilities(bad: object) -> None:
    with pytest.raises(bkt.InvalidProbabilityError):
        bkt.predict_correct(bad, G, S)  # type: ignore[arg-type]
    with pytest.raises(bkt.InvalidProbabilityError):
        bkt.learn_transition(0.5, bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["p_init", "p_learn", "p_guess", "p_slip"])
@pytest.mark.parametrize("bad", [-0.1, 1.5, math.nan, math.inf])
def test_parameter_contract_rejects_out_of_range(field: str, bad: float) -> None:
    values = DEFAULT_PARAMETERS.model_dump() | {field: bad}
    with pytest.raises(ValidationError):
        BKTParameters.model_validate(values)


def test_parameter_contract_documented_restrictions() -> None:
    base = DEFAULT_PARAMETERS.model_dump()
    with pytest.raises(ValidationError, match="identifiable"):
        BKTParameters.model_validate(base | {"p_guess": 0.6, "p_slip": 0.4})
    with pytest.raises(ValidationError, match="calibrated"):
        BKTParameters.model_validate(base | {"calibrated": True})
    assert DEFAULT_PARAMETERS.source == "hand_set" and DEFAULT_PARAMETERS.calibrated is False
    # Endpoint parameters are allowed when the model stays identifiable.
    BKTParameters.model_validate(base | {"p_init": 0.0, "p_learn": 1.0, "p_guess": 0.0})


def test_predictor_predicts_before_it_observes() -> None:
    predictor = BKTPredictor(LEARNER)
    first = predictor.observe(event("o1", True, "problem.a"))
    assert first.status == "counted" and first.sequence == 1
    assert first.prediction is not None
    assert close(first.prediction.p_correct, 0.38)
    assert close(first.prediction.latent_knowledge or -1, 0.2)
    assert close(first.p_known_posterior or -1, 9 / 19)
    assert close(first.p_known_after or -1, 10 / 19)
    second = predictor.observe(event("o2", True, "problem.b"))
    assert second.prediction is not None
    assert close(second.prediction.latent_knowledge or -1, 10 / 19)
    assert close(second.p_known_posterior or -1, 0.8)
    assert close(predictor.p_known(CONCEPT), 0.82)


def test_excluded_and_duplicate_events_leave_state_unchanged() -> None:
    predictor = BKTPredictor(LEARNER)
    predictor.observe(event("o1", True, "problem.a"))
    before = predictor.save()
    assert predictor.observe(event("o1", True, "problem.a")).status == "already_observed"
    assert predictor.observe(event("o2", False, "problem.a")).status == "duplicate_opportunity"
    ineligible = predictor.observe(event("o3", True, eligible=False))
    assert ineligible.status == "ineligible" and ineligible.prediction is None
    assert predictor.save() == before


def test_impossible_observation_does_not_update_predictor() -> None:
    params = BKTParameters.model_validate(
        DEFAULT_PARAMETERS.model_dump()
        | {"parameter_version": "edge.v1", "p_init": 0.0, "p_guess": 0.0}
    )
    predictor = BKTPredictor(LEARNER, params)
    update = predictor.observe(event("o1", True))
    assert update.status == "impossible_observation"
    assert update.p_known_after is None and update.sequence is None
    assert predictor.p_known(CONCEPT) == 0.0
    assert predictor.counted_opportunities(CONCEPT) == []


def test_save_load_reset_round_trip() -> None:
    predictor = BKTPredictor(LEARNER)
    predictor.observe(event("o1", True, "problem.a"))
    snapshot = predictor.save()
    restored = BKTPredictor.from_snapshot(snapshot.model_validate_json(snapshot.model_dump_json()))
    restored.observe(event("o2", True, "problem.b"))
    predictor.observe(event("o2", True, "problem.b"))
    assert restored.save() == predictor.save()
    assert close(restored.p_known(CONCEPT), 0.82)
    predictor.reset()
    assert predictor.p_known(CONCEPT) == 0.2 and predictor.save().concepts == []


def test_load_refuses_other_parameters_learner_or_history() -> None:
    snapshot = BKTPredictor(LEARNER).save()
    other = BKTParameters.model_validate(
        DEFAULT_PARAMETERS.model_dump() | {"parameter_version": "x.v2", "p_learn": 0.0}
    )
    with pytest.raises(SnapshotMismatchError):
        BKTPredictor(LEARNER, other).load(snapshot)
    with pytest.raises(SnapshotMismatchError):
        BKTPredictor("someone-else").load(snapshot)
    with pytest.raises(SnapshotMismatchError):
        BKTPredictor(LEARNER).observe(event("o9", True, learner="someone-else"))
