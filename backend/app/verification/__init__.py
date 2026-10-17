"""Bounded, allowlisted algebra verification and separate explanation-rubric hooks.

Public entry points: ``check_step`` (next-step equivalence), ``check_solution`` and
``assess_input``. All parsing goes through ``app.verification.parser``; nothing here calls
``eval``, ``sympify`` or ``parse_expr`` on user or generated text.
"""

from app.verification.bounds import BOUNDS_VERSION, DEFAULT_BOUNDS, VerificationBounds
from app.verification.contracts import (
    TYPED_STUDENT_WORK,
    InputAssessment,
    SolutionSet,
    VerificationResult,
    WorkSource,
)
from app.verification.explanation import (
    DISTRIBUTION_EXPLANATION_RUBRIC,
    ExplanationJudge,
    ExplanationJudgment,
    ExplanationRubric,
    KeywordExplanationJudge,
    validate_judgment,
)
from app.verification.verifier import assess_input, check_solution, check_step

__all__ = [
    "BOUNDS_VERSION",
    "DEFAULT_BOUNDS",
    "DISTRIBUTION_EXPLANATION_RUBRIC",
    "TYPED_STUDENT_WORK",
    "ExplanationJudge",
    "ExplanationJudgment",
    "ExplanationRubric",
    "InputAssessment",
    "KeywordExplanationJudge",
    "SolutionSet",
    "VerificationBounds",
    "VerificationResult",
    "WorkSource",
    "assess_input",
    "check_solution",
    "check_step",
    "validate_judgment",
]
