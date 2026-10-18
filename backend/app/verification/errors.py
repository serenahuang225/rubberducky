"""Typed rejection raised inside the parser and converted into a result at the boundary."""

from typing import Literal

InputStatus = Literal[
    "parsed", "malformed", "unsupported", "excessive", "undefined", "not_assessable"
]
InputReason = Literal[
    "ok",
    "empty",
    "too_long",
    "too_many_tokens",
    "too_many_nodes",
    "too_deep",
    "too_many_operations",
    "number_too_large",
    "too_many_decimal_places",
    "coefficient_too_large",
    "too_many_variables",
    "disallowed_character",
    "malformed_number",
    "malformed_equality",
    "unexpected_token",
    "unbalanced_parentheses",
    "empty_side",
    "unsupported_function",
    "unsupported_identifier",
    "non_finite",
    "exponent",
    "inequality",
    "nonlinear",
    "degree_too_high",
    "variable_in_denominator",
    "division_by_zero",
    "unconfirmed_ink",
    "tutor_authored",
    "not_an_equation",
]


class RejectedInputError(Exception):
    def __init__(self, status: InputStatus, reason: InputReason, detail: str) -> None:
        super().__init__(detail)
        self.status: InputStatus = status
        self.reason: InputReason = reason
        self.detail = detail
