"""Typed verification outcomes.

A verification result is a mathematical claim only (``judgment_scope='mathematical'``). It
says nothing about reasoning quality, independence or transfer; pedagogy layers decide those
from separate evidence. ``status='unknown'`` covers every input that could not be checked and
is never a statement that the learner is wrong.
"""

from typing import Literal

from app.schemas.common import ContractModel
from app.verification.errors import InputReason, InputStatus

VerificationStatus = Literal["valid", "invalid", "unknown"]
CheckKind = Literal["expression_step", "equation_step", "solution"]
CheckReason = Literal[
    "equivalent",
    "not_equivalent",
    "different_variable",
    "kind_mismatch",
    "not_solved_form",
    "solution_matches",
    "solution_differs",
    "reference_not_checkable",
    "candidate_not_checkable",
]
AuthorRole = Literal["student", "tutor"]
WorkInputMode = Literal["typed", "confirmed_ink", "unconfirmed_ink"]
SolutionKind = Literal["single", "all", "none"]


class WorkSource(ContractModel):
    """Who produced the candidate text and how. Only student typed/confirmed work is assessed."""

    author_role: AuthorRole
    input_mode: WorkInputMode


TYPED_STUDENT_WORK = WorkSource(author_role="student", input_mode="typed")


class InputAssessment(ContractModel):
    status: InputStatus
    reason: InputReason
    detail: str | None = None
    normalized: str | None = None


class SolutionSet(ContractModel):
    kind: SolutionKind
    variable: str | None = None
    value: str | None = None


class VerificationResult(ContractModel):
    schema_version: Literal["verification-result.v1"] = "verification-result.v1"
    check: CheckKind
    status: VerificationStatus
    reason: CheckReason
    judgment_scope: Literal["mathematical"] = "mathematical"
    reference: InputAssessment
    candidate: InputAssessment
    reference_solution: SolutionSet | None = None
    candidate_solution: SolutionSet | None = None
    bounds_version: str
