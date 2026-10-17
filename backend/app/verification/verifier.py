"""Exact equivalence checks for distribution steps and one-variable linear equations.

Two expressions are equivalent when their expanded difference is zero. Two linear equations
are equivalent when they have the same solution set (one value, every value, or none) in the
same variable. A solution claim must be in solved form (``x = 4``, ``4 = x`` or ``4``).
"""

from dataclasses import dataclass

import sympy

from app.verification.bounds import DEFAULT_BOUNDS, VerificationBounds
from app.verification.contracts import (
    TYPED_STUDENT_WORK,
    CheckKind,
    CheckReason,
    InputAssessment,
    SolutionSet,
    VerificationResult,
    VerificationStatus,
    WorkSource,
)
from app.verification.errors import RejectedInputError
from app.verification.parser import Parsed, ParsedEquation, ParsedExpression, parse_math


@dataclass(frozen=True, slots=True)
class _Solved:
    kind: str
    variable: str | None
    value: sympy.Rational | None

    def contract(self) -> SolutionSet:
        value = None if self.value is None else str(self.value)
        return SolutionSet.model_validate(
            {"kind": self.kind, "variable": self.variable, "value": value}
        )


def _render(parsed: Parsed) -> str:
    if isinstance(parsed, ParsedExpression):
        return str(sympy.sstr(parsed.expr))
    return f"{sympy.sstr(parsed.left)} = {sympy.sstr(parsed.right)}"


def assess_input(
    text: str, bounds: VerificationBounds = DEFAULT_BOUNDS
) -> tuple[InputAssessment, Parsed | None]:
    try:
        parsed = parse_math(text, bounds)
    except RejectedInputError as rejection:
        return (
            InputAssessment(
                status=rejection.status, reason=rejection.reason, detail=rejection.detail
            ),
            None,
        )
    return InputAssessment(status="parsed", reason="ok", normalized=_render(parsed)), parsed


def _gate(source: WorkSource) -> InputAssessment | None:
    if source.author_role != "student":
        return InputAssessment(
            status="not_assessable", reason="tutor_authored", detail="tutor work is not assessed"
        )
    if source.input_mode == "unconfirmed_ink":
        return InputAssessment(
            status="not_assessable",
            reason="unconfirmed_ink",
            detail="confirm or type the ink before it is checked",
        )
    return None


def _solve(equation: ParsedEquation) -> _Solved:
    difference = sympy.expand(equation.left - equation.right)
    if not equation.variables:
        return _Solved("all" if difference == 0 else "none", None, None)
    (name,) = equation.variables
    symbol = sympy.Symbol(name)
    slope = sympy.Rational(difference.coeff(symbol, 1))
    intercept = sympy.Rational(difference.coeff(symbol, 0))
    if slope != 0:
        return _Solved("single", name, sympy.Rational(-intercept / slope))
    return _Solved("all" if intercept == 0 else "none", name, None)


def _one_variable(parsed: ParsedEquation) -> InputAssessment | None:
    if len(parsed.variables) > 1:
        return InputAssessment(
            status="unsupported",
            reason="too_many_variables",
            detail="equations are checked in one variable",
        )
    return None


def _result(
    check: CheckKind,
    status: VerificationStatus,
    reason: CheckReason,
    reference: InputAssessment,
    candidate: InputAssessment,
    bounds: VerificationBounds,
    reference_solution: _Solved | None = None,
    candidate_solution: _Solved | None = None,
) -> VerificationResult:
    return VerificationResult(
        check=check,
        status=status,
        reason=reason,
        reference=reference,
        candidate=candidate,
        reference_solution=None if reference_solution is None else reference_solution.contract(),
        candidate_solution=None if candidate_solution is None else candidate_solution.contract(),
        bounds_version=bounds.version,
    )


def _prepare(
    reference_text: str,
    candidate_text: str,
    source: WorkSource,
    bounds: VerificationBounds,
) -> tuple[InputAssessment, Parsed | None, InputAssessment, Parsed | None]:
    reference, reference_parsed = assess_input(reference_text, bounds)
    gated = _gate(source)
    if gated is not None:
        # Unconfirmed ink and tutor strokes are never parsed, so they cannot become answers.
        return reference, reference_parsed, gated, None
    candidate, candidate_parsed = assess_input(candidate_text, bounds)
    return reference, reference_parsed, candidate, candidate_parsed


def check_step(
    reference_text: str,
    candidate_text: str,
    source: WorkSource = TYPED_STUDENT_WORK,
    bounds: VerificationBounds = DEFAULT_BOUNDS,
) -> VerificationResult:
    """Is ``candidate_text`` an equivalent rewrite of ``reference_text``?"""
    reference, ref, candidate, cand = _prepare(reference_text, candidate_text, source, bounds)
    check: CheckKind = "equation_step" if isinstance(ref, ParsedEquation) else "expression_step"
    if ref is None:
        return _result(check, "unknown", "reference_not_checkable", reference, candidate, bounds)
    if cand is None:
        return _result(check, "unknown", "candidate_not_checkable", reference, candidate, bounds)

    if isinstance(ref, ParsedExpression) and isinstance(cand, ParsedExpression):
        equal = sympy.expand(ref.expr - cand.expr) == 0
        status: VerificationStatus = "valid" if equal else "invalid"
        return _result(
            check, status, "equivalent" if equal else "not_equivalent", reference, candidate, bounds
        )
    if isinstance(ref, ParsedEquation) and isinstance(cand, ParsedEquation):
        if (problem := _one_variable(ref)) is not None:
            return _result(check, "unknown", "reference_not_checkable", problem, candidate, bounds)
        if (problem := _one_variable(cand)) is not None:
            return _result(check, "unknown", "candidate_not_checkable", reference, problem, bounds)
        ref_solution, cand_solution = _solve(ref), _solve(cand)
        if ref.variables and cand.variables and ref.variables != cand.variables:
            return _result(
                check,
                "invalid",
                "different_variable",
                reference,
                candidate,
                bounds,
                ref_solution,
                cand_solution,
            )
        same = (ref_solution.kind, ref_solution.value) == (cand_solution.kind, cand_solution.value)
        return _result(
            check,
            "valid" if same else "invalid",
            "equivalent" if same else "not_equivalent",
            reference,
            candidate,
            bounds,
            ref_solution,
            cand_solution,
        )
    return _result(check, "unknown", "kind_mismatch", reference, candidate, bounds)


def _solved_form(answer: Parsed) -> tuple[str | None, sympy.Rational] | None:
    if isinstance(answer, ParsedExpression):
        if answer.variables:
            return None
        return None, sympy.Rational(answer.expr)
    for lone, other in ((answer.left, answer.right), (answer.right, answer.left)):
        if isinstance(lone, sympy.Symbol) and not other.free_symbols:
            return lone.name, sympy.Rational(other)
    return None


def check_solution(
    equation_text: str,
    answer_text: str,
    source: WorkSource = TYPED_STUDENT_WORK,
    bounds: VerificationBounds = DEFAULT_BOUNDS,
) -> VerificationResult:
    """Is ``answer_text`` the unique solution of the one-variable ``equation_text``?"""
    reference, ref, candidate, answer = _prepare(equation_text, answer_text, source, bounds)
    if not isinstance(ref, ParsedEquation):
        if ref is not None:
            reference = InputAssessment(
                status="unsupported",
                reason="not_an_equation",
                detail="a solution needs an equation",
                normalized=reference.normalized,
            )
        return _result(
            "solution", "unknown", "reference_not_checkable", reference, candidate, bounds
        )
    if (problem := _one_variable(ref)) is not None:
        return _result("solution", "unknown", "reference_not_checkable", problem, candidate, bounds)
    if answer is None:
        return _result(
            "solution", "unknown", "candidate_not_checkable", reference, candidate, bounds
        )
    ref_solution = _solve(ref)
    solved = _solved_form(answer)
    if solved is None:
        return _result(
            "solution", "unknown", "not_solved_form", reference, candidate, bounds, ref_solution
        )
    variable, value = solved
    cand_solution = _Solved("single", variable or ref_solution.variable, value)
    if variable is not None and variable != (ref_solution.variable or variable):
        return _result(
            "solution",
            "invalid",
            "different_variable",
            reference,
            candidate,
            bounds,
            ref_solution,
            cand_solution,
        )
    matches = ref_solution.kind == "single" and ref_solution.value == value
    return _result(
        "solution",
        "valid" if matches else "invalid",
        "solution_matches" if matches else "solution_differs",
        reference,
        candidate,
        bounds,
        ref_solution,
        cand_solution,
    )
