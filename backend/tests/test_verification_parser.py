import inspect
import pkgutil
import time
from dataclasses import replace

import pytest
import sympy
import sympy.parsing.sympy_parser

import app.verification as verification
from app.verification import DEFAULT_BOUNDS, VerificationBounds, assess_input, check_step
from app.verification.parser import ParsedEquation, ParsedExpression, parse_math


def status_reason(text: str, bounds: VerificationBounds = DEFAULT_BOUNDS) -> tuple[str, str]:
    assessment, _ = assess_input(text, bounds)
    return assessment.status, assessment.reason


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        ("2(x + 3)", "2*x + 6"),
        ("2x+6", "2*x + 6"),
        ("-3(2 - y)", "3*y - 6"),
        ("0.5(4x + 2)", "2*x + 1"),
        ("x/2 + 1", "x/2 + 1"),
        ("(x + 1)(2)", "2*x + 2"),
        ("2\u00d7(x \u2212 3) \u00f7 4", "x/2 - 3/2"),
        ("--x", "x"),
        ("2(x + 3) = 14", "2*x + 6 = 14"),
        ("5 = 2(z - 3) + 1", "5 = 2*z - 5"),
    ],
)
def test_supported_forms_parse_to_exact_expressions(text: str, normalized: str) -> None:
    assessment, parsed = assess_input(text)
    assert (assessment.status, assessment.reason) == ("parsed", "ok")
    assert assessment.normalized == normalized
    assert isinstance(parsed, ParsedExpression | ParsedEquation)


def test_decimals_become_exact_rationals() -> None:
    parsed = parse_math("0.1 + 0.2", DEFAULT_BOUNDS)
    assert isinstance(parsed, ParsedExpression)
    assert parsed.expr == sympy.Rational(3, 10)


@pytest.mark.parametrize(
    ("text", "status", "reason"),
    [
        ("__import__('os').system('ls')", "malformed", "disallowed_character"),
        ("lambda: 1", "unsupported", "unsupported_identifier"),
        ("x; import os", "malformed", "disallowed_character"),
        ("eval(x)", "unsupported", "unsupported_function"),
        ("exec(x)", "unsupported", "unsupported_function"),
        ("sympify(x)", "unsupported", "unsupported_function"),
        ("x.__class__", "malformed", "disallowed_character"),
        ("[x for x in y]", "malformed", "disallowed_character"),
        ("{x}", "malformed", "disallowed_character"),
        ("sin(x)", "unsupported", "unsupported_function"),
        ("sqrt (x)", "unsupported", "unsupported_function"),
        ("Symbol('x')", "unsupported", "unsupported_function"),
        ("os", "unsupported", "unsupported_identifier"),
        ("2x + 6 == 14", "malformed", "malformed_equality"),
        ("x = 2 = 3", "malformed", "malformed_equality"),
        ("= 14", "malformed", "empty_side"),
        ("2x + 6 =", "malformed", "empty_side"),
        ("x < 3", "unsupported", "inequality"),
        ("x != 3", "unsupported", "inequality"),
        ("x^2", "unsupported", "exponent"),
        ("x**2", "unsupported", "exponent"),
        ("x * x", "unsupported", "nonlinear"),
        ("x(x + 1)", "unsupported", "nonlinear"),
        ("x*y", "unsupported", "nonlinear"),
        ("1/x", "unsupported", "variable_in_denominator"),
        ("1/(x - x)", "unsupported", "variable_in_denominator"),
        ("1/0", "undefined", "division_by_zero"),
        ("x/(3 - 3) = 2", "undefined", "division_by_zero"),
        ("4/(2 * 0)", "undefined", "division_by_zero"),
        ("inf", "unsupported", "non_finite"),
        ("-Infinity", "unsupported", "non_finite"),
        ("nan", "unsupported", "non_finite"),
        ("oo", "unsupported", "non_finite"),
        ("\u221e", "unsupported", "non_finite"),
        ("1e309", "malformed", "unexpected_token"),
        ("x2", "malformed", "unexpected_token"),
        ("2 3", "malformed", "unexpected_token"),
        ("2x +", "malformed", "unexpected_token"),
        ("(x + 3", "malformed", "unbalanced_parentheses"),
        ("x + 3)", "malformed", "unbalanced_parentheses"),
        ("()", "malformed", "unexpected_token"),
        ("1..2", "malformed", "malformed_number"),
        ("1.2.3", "malformed", "malformed_number"),
        ("", "malformed", "empty"),
        ("   ", "malformed", "empty"),
        ("x\n+1", "malformed", "disallowed_character"),
        ("\u0663x", "malformed", "disallowed_character"),
        ("a + b + c", "unsupported", "too_many_variables"),
    ],
)
def test_rejected_inputs_return_typed_outcomes(text: str, status: str, reason: str) -> None:
    assessment, parsed = assess_input(text)
    assert (assessment.status, assessment.reason) == (status, reason)
    assert parsed is None
    assert assessment.normalized is None


def test_rejected_input_is_unknown_never_invalid_math() -> None:
    for candidate in ["__import__('os')", "1/0", "x^2", "9" * 50, "sin(x) = 1", "x + = 3"]:
        result = check_step("2(x + 3) = 14", candidate)
        assert result.status == "unknown"
        assert result.reason == "candidate_not_checkable"


def test_character_limit_boundary() -> None:
    at_limit = "x" + "+1" * ((DEFAULT_BOUNDS.max_chars - 1) // 2)
    bounds = replace(DEFAULT_BOUNDS, max_operations=100, max_nodes=200, max_tokens=200)
    assert len(at_limit) <= DEFAULT_BOUNDS.max_chars
    assert status_reason(at_limit, bounds) == ("parsed", "ok")
    padded = at_limit + " " * (DEFAULT_BOUNDS.max_chars - len(at_limit) + 1)
    assert status_reason(padded, bounds) == ("excessive", "too_long")


def test_integer_digit_boundary() -> None:
    assert status_reason("999999x") == ("parsed", "ok")
    assert status_reason("1000000x") == ("excessive", "number_too_large")


def test_decimal_places_boundary() -> None:
    assert status_reason("0.0001x") == ("parsed", "ok")
    assert status_reason("0.00001x") == ("excessive", "too_many_decimal_places")


def test_coefficient_size_boundary() -> None:
    # 999999^3 has 18 digits and is allowed; one more factor exceeds 10^18.
    assert status_reason("999999 * 999999 * 999999 x") == ("parsed", "ok")
    assert status_reason("999999 * 999999 * 999999 * 999999 x") == (
        "excessive",
        "coefficient_too_large",
    )
    assert status_reason("x / 999999 / 999999 / 999999 / 999999") == (
        "excessive",
        "coefficient_too_large",
    )


def test_operation_count_boundary() -> None:
    limit = DEFAULT_BOUNDS.max_operations
    assert status_reason("1" + "+1" * limit) == ("parsed", "ok")
    assert status_reason("1" + "+1" * (limit + 1)) == ("excessive", "too_many_operations")


def test_node_and_token_boundaries() -> None:
    nodes = replace(DEFAULT_BOUNDS, max_nodes=5)
    assert status_reason("1+1+1", nodes) == ("parsed", "ok")
    assert status_reason("1+1+1+1", nodes) == ("excessive", "too_many_nodes")
    tokens = replace(DEFAULT_BOUNDS, max_tokens=5)
    assert status_reason("1+1+1", tokens) == ("parsed", "ok")
    assert status_reason("(1+1+1)", tokens) == ("excessive", "too_many_tokens")


def test_nesting_depth_boundary() -> None:
    # The top-level expression uses one level, each parenthesis pair one more.
    allowed = DEFAULT_BOUNDS.max_depth - 1
    assert status_reason("(" * allowed + "x" + ")" * allowed) == ("parsed", "ok")
    deeper = allowed + 1
    assert status_reason("(" * deeper + "x" + ")" * deeper) == ("excessive", "too_deep")
    assert status_reason("-" * DEFAULT_BOUNDS.max_depth + "x") == ("excessive", "too_deep")


@pytest.mark.parametrize(
    "text",
    [
        "(" * 5000 + "x" + ")" * 5000,
        "9" * 100_000,
        "x" + "+x" * 50_000,
        "-" * 100_000 + "1",
        "2(" * 59 + "x" + ")" * 59,
        "999999" + "*999999" * 19,
    ],
)
def test_adversarial_inputs_are_rejected_quickly(text: str) -> None:
    start = time.perf_counter()
    status, _ = status_reason(text)
    assert status == "excessive"
    assert time.perf_counter() - start < 0.5


def test_largest_allowed_input_is_cheap() -> None:
    text = "2(x + 3) - 0.5(4x - 999999) + 7/8(x - 1) + 3(x + 1) - 9(x - 2) = 1 + x"
    start = time.perf_counter()
    assessment, _ = assess_input(text)
    assert assessment.status == "parsed"
    assert time.perf_counter() - start < 0.5


def test_no_string_ever_reaches_sympify_or_parse_expr(monkeypatch: pytest.MonkeyPatch) -> None:
    # SymPy's own sympify imports parse_expr lazily for string inputs, so patching parse_expr
    # catches strings that reach sympify from anywhere, including SymPy internals.
    original = sympy.sympify

    def guarded(value: object, *args: object, **kwargs: object) -> object:
        if isinstance(value, str):
            raise AssertionError("string passed to sympify")
        return original(value, *args, **kwargs)  # type: ignore[arg-type]

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("parse_expr must not be used")

    monkeypatch.setattr(sympy, "sympify", guarded)
    monkeypatch.setattr(sympy.parsing.sympy_parser, "parse_expr", forbidden)
    assert check_step("2(x + 3) = 14", "2x + 6 = 14").status == "valid"
    assert check_step("5 = 2(z - 3) + 1", "5 = 2z - 6 + 1").status == "valid"
    assert check_step("2(x + 3)", "2x + 3").status == "invalid"


def test_verification_source_has_no_dynamic_evaluation_path() -> None:
    banned = ("eval(", "exec(", "sympify", "parse_expr", "compile(", "__import__", "S(", "lambdify")
    for module in pkgutil.iter_modules(verification.__path__):
        source = inspect.getsource(__import__(f"app.verification.{module.name}", fromlist=["x"]))
        code_lines = [
            line
            for line in source.splitlines()
            if not line.lstrip().startswith(("#", '"', "``")) and "``" not in line
        ]
        for token in banned:
            assert not any(token in line for line in code_lines), (module.name, token)
