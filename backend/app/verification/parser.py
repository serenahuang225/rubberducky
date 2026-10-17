"""Recursive-descent parser that builds SymPy objects through explicit constructors.

Grammar (left-associative, ``*``/``/`` bind tighter than ``+``/``-``)::

    statement := expr ( "=" expr )?
    expr      := term ( ("+" | "-") term )*
    term      := unary ( ("*" | "/") unary | implicit )*
    implicit  := VAR | "(" expr ")"          # only after a number, variable or ")"
    unary     := ("+" | "-") unary | primary
    primary   := NUM | VAR | "(" expr ")"

Implicit multiplication covers ``2x``, ``2(x + 3)`` and ``(x)(2)``; a number after a variable
or ``)`` (``x2``) is malformed. The tree is checked for size, depth, linearity and constant
denominators with exact ``Fraction`` arithmetic before SymPy sees it, so SymPy only constructs
degree-one polynomials. No string is ever passed to ``sympify``/``parse_expr``/``eval``.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import sympy

from app.verification.bounds import VerificationBounds
from app.verification.errors import InputReason, RejectedInputError
from app.verification.lexer import Token, tokenize


@dataclass(frozen=True, slots=True)
class Num:
    value: Fraction


@dataclass(frozen=True, slots=True)
class Var:
    name: str


@dataclass(frozen=True, slots=True)
class Neg:
    operand: Node


@dataclass(frozen=True, slots=True)
class BinOp:
    op: str
    left: Node
    right: Node


Node = Num | Var | Neg | BinOp


@dataclass(frozen=True, slots=True)
class ParsedExpression:
    expr: sympy.Expr
    variables: frozenset[str]


@dataclass(frozen=True, slots=True)
class ParsedEquation:
    left: sympy.Expr
    right: sympy.Expr
    variables: frozenset[str]


Parsed = ParsedExpression | ParsedEquation


class _Parser:
    def __init__(self, tokens: list[Token], bounds: VerificationBounds) -> None:
        self._tokens = tokens
        self._pos = 0
        self._bounds = bounds
        self._nodes = 0
        self._operations = 0

    def _peek(self) -> Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> Token:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _count(self, node: Node) -> Node:
        self._nodes += 1
        if isinstance(node, Neg | BinOp):
            self._operations += 1
        if self._nodes > self._bounds.max_nodes:
            raise RejectedInputError(
                "excessive", "too_many_nodes", f"over {self._bounds.max_nodes} nodes"
            )
        if self._operations > self._bounds.max_operations:
            raise RejectedInputError(
                "excessive",
                "too_many_operations",
                f"over {self._bounds.max_operations} operations",
            )
        return node

    def _enter(self, depth: int) -> int:
        if depth >= self._bounds.max_depth:
            limit = self._bounds.max_depth
            raise RejectedInputError("excessive", "too_deep", f"nesting deeper than {limit}")
        return depth + 1

    def parse_side(self) -> Node:
        if self._peek() is None or self._peek_kind("eq"):
            raise RejectedInputError(
                "malformed", "empty_side", "each side of '=' needs an expression"
            )
        return self._expr(0)

    def _peek_kind(self, kind: str) -> bool:
        token = self._peek()
        return token is not None and token.kind == kind

    def _expr(self, depth: int) -> Node:
        depth = self._enter(depth)
        node = self._term(depth)
        while (token := self._peek()) is not None and token.kind == "op" and token.text in "+-":
            self._advance()
            node = self._count(BinOp(token.text, node, self._term(depth)))
        return node

    def _term(self, depth: int) -> Node:
        node = self._unary(depth)
        while (token := self._peek()) is not None:
            if token.kind == "op" and token.text in "*/":
                self._advance()
                node = self._count(BinOp(token.text, node, self._unary(depth)))
            elif token.kind in ("var", "lparen"):
                node = self._count(BinOp("*", node, self._primary(depth)))
            elif token.kind == "num":
                raise RejectedInputError(
                    "malformed", "unexpected_token", "a number cannot follow here"
                )
            else:
                break
        return node

    def _unary(self, depth: int) -> Node:
        token = self._peek()
        if token is not None and token.kind == "op" and token.text in "+-":
            self._advance()
            operand = self._unary(self._enter(depth))
            if token.text == "+":
                return operand
            return self._count(Neg(operand))
        return self._primary(depth)

    def _primary(self, depth: int) -> Node:
        token = self._peek()
        if token is None:
            raise RejectedInputError("malformed", "unexpected_token", "expression ends too early")
        if token.kind == "num":
            self._advance()
            return self._count(Num(Fraction(token.text)))
        if token.kind == "var":
            self._advance()
            return self._count(Var(token.text))
        if token.kind == "lparen":
            self._advance()
            if self._peek_kind("rparen"):
                raise RejectedInputError("malformed", "unexpected_token", "empty parentheses")
            inner = self._expr(depth)
            if not self._peek_kind("rparen"):
                raise RejectedInputError("malformed", "unbalanced_parentheses", "missing ')'")
            self._advance()
            return inner
        if token.kind == "rparen":
            raise RejectedInputError("malformed", "unbalanced_parentheses", "unexpected ')'")
        raise RejectedInputError("malformed", "unexpected_token", f"unexpected '{token.text}'")


def _check_size(value: Fraction, bounds: VerificationBounds) -> Fraction:
    limit = 10**bounds.max_coefficient_digits
    if abs(value.numerator) >= limit or value.denominator >= limit:
        raise RejectedInputError("excessive", "coefficient_too_large", "a number grows too large")
    return value


def _analyze(node: Node, bounds: VerificationBounds) -> tuple[int, Fraction | None]:
    """Return (polynomial degree upper bound, exact value if the subtree is constant)."""
    if isinstance(node, Num):
        return 0, _check_size(node.value, bounds)
    if isinstance(node, Var):
        return 1, None
    if isinstance(node, Neg):
        degree, value = _analyze(node.operand, bounds)
        return degree, None if value is None else -value
    left_degree, left_value = _analyze(node.left, bounds)
    right_degree, right_value = _analyze(node.right, bounds)
    if node.op in "+-":
        degree = max(left_degree, right_degree)
        if left_value is None or right_value is None:
            return degree, None
        total = left_value + right_value if node.op == "+" else left_value - right_value
        return degree, _check_size(total, bounds)
    if node.op == "*":
        degree = left_degree + right_degree
        if degree > 1:
            raise RejectedInputError(
                "unsupported", "nonlinear", "only linear expressions are checked"
            )
        if left_value is None or right_value is None:
            return degree, None
        return degree, _check_size(left_value * right_value, bounds)
    # Division: only by a constant. The AST degree is an upper bound, so "1/(x - x)" is
    # reported unsupported rather than simplified.
    if right_degree > 0 or right_value is None:
        raise RejectedInputError("unsupported", "variable_in_denominator", "divide only by numbers")
    if right_value == 0:
        raise RejectedInputError("undefined", "division_by_zero", "division by zero is undefined")
    if left_value is None:
        return left_degree, None
    return left_degree, _check_size(left_value / right_value, bounds)


def _variables(node: Node, found: set[str]) -> set[str]:
    if isinstance(node, Var):
        found.add(node.name)
    elif isinstance(node, Neg):
        _variables(node.operand, found)
    elif isinstance(node, BinOp):
        _variables(node.left, found)
        _variables(node.right, found)
    return found


def _rational(value: Fraction) -> sympy.Rational:
    return sympy.Rational(value.numerator, value.denominator)


def _build(node: Node, symbols: dict[str, sympy.Symbol]) -> sympy.Expr:
    if isinstance(node, Num):
        return _rational(node.value)
    if isinstance(node, Var):
        return symbols[node.name]
    if isinstance(node, Neg):
        return sympy.Mul(sympy.Integer(-1), _build(node.operand, symbols))
    left = _build(node.left, symbols)
    right = _build(node.right, symbols)
    if node.op == "+":
        return sympy.Add(left, right)
    if node.op == "-":
        return sympy.Add(left, sympy.Mul(sympy.Integer(-1), right))
    if node.op == "*":
        return sympy.Mul(left, right)
    return sympy.Mul(left, sympy.Pow(right, sympy.Integer(-1)))


def _check_coefficients(expr: sympy.Expr, bounds: VerificationBounds) -> sympy.Expr:
    expanded = sympy.expand(expr)
    for coefficient in expanded.as_coefficients_dict().values():
        rational = sympy.Rational(coefficient)
        _check_size(Fraction(int(rational.p), int(rational.q)), bounds)
    return expanded


def parse_math(raw: str, bounds: VerificationBounds) -> Parsed:
    """Parse one typed expression or equation, raising ``RejectedInputError`` for anything else."""
    tokens = tokenize(raw, bounds)
    equals = sum(1 for token in tokens if token.kind == "eq")
    if equals > 1:
        raise RejectedInputError("malformed", "malformed_equality", "use exactly one '='")

    parser = _Parser(tokens, bounds)
    sides = [parser.parse_side()]
    if parser._peek_kind("eq"):
        parser._advance()
        sides.append(parser.parse_side())
    leftover = parser._peek()
    if leftover is not None:
        reason: InputReason = (
            "unbalanced_parentheses" if leftover.kind == "rparen" else "unexpected_token"
        )
        raise RejectedInputError("malformed", reason, f"unexpected '{leftover.text}'")

    for side in sides:
        _analyze(side, bounds)
    names: set[str] = set()
    for side in sides:
        _variables(side, names)
    if len(names) > bounds.max_variables:
        raise RejectedInputError(
            "unsupported", "too_many_variables", f"more than {bounds.max_variables} variables"
        )
    symbols = {name: sympy.Symbol(name) for name in sorted(names)}
    built = [_check_coefficients(_build(side, symbols), bounds) for side in sides]
    variables = frozenset(names)
    if len(built) == 1:
        return ParsedExpression(built[0], variables)
    return ParsedEquation(built[0], built[1], variables)
