"""Exact checks for polynomial derivatives, antiderivatives and one gradient.

Powers are opt-in here. The algebra checker still rejects ``^``. An antiderivative may
end in ``+ C`` or any constant; those answers match. A gradient is a pair of partial
derivatives. Nothing in this module calls ``sympify`` or ``parse_expr``.
"""

import sympy

from app.verification.bounds import DEFAULT_BOUNDS, VerificationBounds
from app.verification.contracts import (
    TYPED_STUDENT_WORK,
    InputAssessment,
    VerificationResult,
    VerificationStatus,
    WorkSource,
)
from app.verification.errors import RejectedInputError
from app.verification.parser import ParsedExpression, parse_math

MAX_POLY_DEGREE = 6


def parse_polynomial(
    text: str, bounds: VerificationBounds = DEFAULT_BOUNDS
) -> ParsedExpression:
    parsed = parse_math(text, bounds, max_degree=MAX_POLY_DEGREE, allow_powers=True)
    if not isinstance(parsed, ParsedExpression):
        raise RejectedInputError(
            "unsupported", "not_an_equation", "write an expression, not an equation"
        )
    return parsed


def _parsed_assessment(text: str, bounds: VerificationBounds) -> tuple[InputAssessment, ParsedExpression | None]:
    try:
        parsed = parse_polynomial(text, bounds)
    except RejectedInputError as rejection:
        return (
            InputAssessment(
                status=rejection.status, reason=rejection.reason, detail=rejection.detail
            ),
            None,
        )
    return (
        InputAssessment(status="parsed", reason="ok", normalized=str(sympy.sstr(parsed.expr))),
        parsed,
    )


def _result(
    status: VerificationStatus,
    reason: str,
    reference: InputAssessment,
    candidate: InputAssessment,
    bounds: VerificationBounds,
) -> VerificationResult:
    return VerificationResult(
        check="solution",
        status=status,
        reason=reason,  # type: ignore[arg-type]
        reference=reference,
        candidate=candidate,
        bounds_version=bounds.version,
    )


def _same(left: sympy.Expr, right: sympy.Expr) -> bool:
    return sympy.expand(left - right) == 0


def check_derivative(
    expression: str,
    candidate: str,
    variable: str,
    source: WorkSource = TYPED_STUDENT_WORK,
    bounds: VerificationBounds = DEFAULT_BOUNDS,
) -> VerificationResult:
    """Is ``candidate`` the derivative of ``expression`` with respect to ``variable``?"""
    del source
    reference, ref = _parsed_assessment(expression, bounds)
    candidate_view, cand = _parsed_assessment(candidate, bounds)
    if ref is None:
        return _result("unknown", "reference_not_checkable", reference, candidate_view, bounds)
    if cand is None:
        return _result("unknown", "candidate_not_checkable", reference, candidate_view, bounds)
    if ref.variables - {variable} or cand.variables - {variable}:
        return _result("invalid", "different_variable", reference, candidate_view, bounds)
    derivative = sympy.diff(ref.expr, sympy.Symbol(variable))
    matched = _same(derivative, cand.expr)
    return _result(
        "valid" if matched else "invalid",
        "solution_matches" if matched else "solution_differs",
        reference,
        candidate_view,
        bounds,
    )


def _constant_body(expr: sympy.Expr) -> sympy.Expr | None:
    symbol = sympy.Symbol("C")
    if symbol not in expr.free_symbols:
        return expr
    if sympy.degree(expr, symbol) > 1:
        return None
    coefficient = expr.coeff(symbol)
    if coefficient.free_symbols:
        return None
    return sympy.expand(expr.subs(symbol, 0))


def check_integral(
    expression: str,
    candidate: str,
    variable: str,
    source: WorkSource = TYPED_STUDENT_WORK,
    bounds: VerificationBounds = DEFAULT_BOUNDS,
) -> VerificationResult:
    """Is ``candidate`` an antiderivative of ``expression``?

    ``+ C`` and ``+`` any number are the same answer. ``C`` may not be multiplied by
    the variable.
    """
    del source
    reference, ref = _parsed_assessment(expression, bounds)
    candidate_view, cand = _parsed_assessment(candidate, bounds)
    if ref is None:
        return _result("unknown", "reference_not_checkable", reference, candidate_view, bounds)
    if cand is None:
        return _result("unknown", "candidate_not_checkable", reference, candidate_view, bounds)
    if ref.variables - {variable} or cand.variables - {variable, "C"}:
        return _result("invalid", "different_variable", reference, candidate_view, bounds)
    body = _constant_body(cand.expr)
    if body is None:
        return _result("invalid", "solution_differs", reference, candidate_view, bounds)
    recovered = sympy.diff(body, sympy.Symbol(variable))
    matched = _same(recovered, ref.expr)
    return _result(
        "valid" if matched else "invalid",
        "solution_matches" if matched else "solution_differs",
        reference,
        candidate_view,
        bounds,
    )


def _split_pair(text: str) -> tuple[str, str] | None:
    body = text.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    depth = 0
    for index, character in enumerate(body):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            left, right = body[:index].strip(), body[index + 1 :].strip()
            if left and right and "," not in right:
                return left, right
            return None
    return None


def check_gradient(
    expression: str,
    candidate: str,
    variables: tuple[str, str] = ("x", "y"),
    source: WorkSource = TYPED_STUDENT_WORK,
    bounds: VerificationBounds = DEFAULT_BOUNDS,
) -> VerificationResult:
    """Is ``candidate`` the gradient of ``expression``, written ``(dx, dy)``?"""
    del source
    reference, ref = _parsed_assessment(expression, bounds)
    pair = _split_pair(candidate)
    if ref is None:
        empty = InputAssessment(status="unsupported", reason="not_an_equation", detail=None)
        return _result("unknown", "reference_not_checkable", reference, empty, bounds)
    if pair is None:
        view = InputAssessment(
            status="unsupported",
            reason="unexpected_token",
            detail="write the gradient as a pair (x part, y part)",
        )
        return _result("unknown", "candidate_not_checkable", reference, view, bounds)
    first, first_parsed = _parsed_assessment(pair[0], bounds)
    second, second_parsed = _parsed_assessment(pair[1], bounds)
    candidate_view = InputAssessment(
        status="parsed" if first_parsed is not None and second_parsed is not None else "unsupported",
        reason="ok" if first_parsed is not None and second_parsed is not None else "unexpected_token",
        normalized=None
        if first_parsed is None or second_parsed is None
        else f"({first.normalized}, {second.normalized})",
    )
    if first_parsed is None or second_parsed is None:
        return _result("unknown", "candidate_not_checkable", reference, candidate_view, bounds)
    allowed = set(variables)
    if ref.variables - allowed or first_parsed.variables - allowed or second_parsed.variables - allowed:
        return _result("invalid", "different_variable", reference, candidate_view, bounds)
    x_symbol, y_symbol = sympy.Symbol(variables[0]), sympy.Symbol(variables[1])
    matched = _same(sympy.diff(ref.expr, x_symbol), first_parsed.expr) and _same(
        sympy.diff(ref.expr, y_symbol), second_parsed.expr
    )
    return _result(
        "valid" if matched else "invalid",
        "solution_matches" if matched else "solution_differs",
        reference,
        candidate_view,
        bounds,
    )
