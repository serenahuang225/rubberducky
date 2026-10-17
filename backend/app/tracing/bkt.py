"""Bayesian Knowledge Tracing (BKT) arithmetic as small, readable NumPy functions.

Quantities, all probabilities in [0, 1]:

* ``p_known`` (P(L_t)): latent probability the skill is known *before* opportunity t.
* ``p_learn`` (T): chance of moving from unknown to known after an opportunity. This
  standard BKT variant has no forgetting.
* ``p_guess`` (g): P(correct response | skill not known).
* ``p_slip`` (s): P(incorrect response | skill known).

Guess and slip describe uncertainty in a single response. They are not traits, diagnoses or
labels of the learner.

Predicted correctness ``p(1-s) + (1-p)g`` is a *different* quantity from ``p_known``: the
first is a probability about the next observable response, the second about a latent state.

Impossible observations: if the observed response has zero probability under the current
state (for example ``p=0, g=0`` and a correct answer, or ``p=1, s=0`` and an incorrect one),
Bayes' rule would divide zero by zero. Those functions return :class:`ImpossibleObservation`
instead of NaN or an invented probability, and callers must leave the state unchanged.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np


class InvalidProbabilityError(ValueError):
    """A BKT input is not a finite real number in [0, 1]."""


@dataclass(frozen=True)
class ImpossibleObservation:
    """The observed response had zero likelihood under the model; no update is defined."""

    observed_correct: bool
    detail: str
    reason: Literal["zero_likelihood"] = "zero_likelihood"


def require_probability(name: str, value: object) -> np.float64:
    # bool is a subclass of int; True/False as a probability is almost always a bug.
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise InvalidProbabilityError(f"{name} must be a real number, got {type(value).__name__}")
    number = np.float64(value)
    if not np.isfinite(number):
        raise InvalidProbabilityError(f"{name} must be finite, got {value!r}")
    if number < 0.0 or number > 1.0:
        raise InvalidProbabilityError(f"{name} must lie in [0, 1], got {value!r}")
    return number


def predict_correct(p_known: float, p_guess: float, p_slip: float) -> float:
    """P(correct) = p(1 - s) + (1 - p)g, computed before the response is seen."""
    p = require_probability("p_known", p_known)
    g = require_probability("p_guess", p_guess)
    s = require_probability("p_slip", p_slip)
    return float(p * (1.0 - s) + (1.0 - p) * g)


def _bayes(
    numerator: np.float64, denominator: np.float64, observed_correct: bool, detail: str
) -> float | ImpossibleObservation:
    if denominator <= 0.0:
        return ImpossibleObservation(observed_correct=observed_correct, detail=detail)
    return float(np.clip(numerator / denominator, 0.0, 1.0))


def posterior_if_correct(
    p_known: float, p_guess: float, p_slip: float
) -> float | ImpossibleObservation:
    """P(known | correct) = p(1 - s) / [p(1 - s) + (1 - p)g]."""
    p = require_probability("p_known", p_known)
    g = require_probability("p_guess", p_guess)
    s = require_probability("p_slip", p_slip)
    known_and_correct = p * (1.0 - s)
    unknown_and_correct = (1.0 - p) * g
    return _bayes(
        known_and_correct,
        known_and_correct + unknown_and_correct,
        True,
        "a correct response has zero probability (known learners always slip and "
        "unknown learners never guess)",
    )


def posterior_if_incorrect(
    p_known: float, p_guess: float, p_slip: float
) -> float | ImpossibleObservation:
    """P(known | incorrect) = ps / [ps + (1 - p)(1 - g)]."""
    p = require_probability("p_known", p_known)
    g = require_probability("p_guess", p_guess)
    s = require_probability("p_slip", p_slip)
    known_and_incorrect = p * s
    unknown_and_incorrect = (1.0 - p) * (1.0 - g)
    return _bayes(
        known_and_incorrect,
        known_and_incorrect + unknown_and_incorrect,
        False,
        "an incorrect response has zero probability (known learners never slip and "
        "unknown learners always guess correctly)",
    )


def posterior(
    p_known: float, correct: bool, p_guess: float, p_slip: float
) -> float | ImpossibleObservation:
    if correct:
        return posterior_if_correct(p_known, p_guess, p_slip)
    return posterior_if_incorrect(p_known, p_guess, p_slip)


def learn_transition(p_known_posterior: float, p_learn: float) -> float:
    """P(L_{t+1}) = posterior + (1 - posterior)T: the chance of learning from the opportunity."""
    post = require_probability("p_known_posterior", p_known_posterior)
    t = require_probability("p_learn", p_learn)
    return float(post + (1.0 - post) * t)
