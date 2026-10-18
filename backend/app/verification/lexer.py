"""Allowlisted tokenizer for typed algebra.

Only digits, single ASCII letters, ``+ - * / ( ) =`` and spaces are accepted. A few common
typographic symbols are mapped explicitly. Anything else is rejected with a typed reason; the
text is never handed to Python or SymPy for interpretation.
"""

from dataclasses import dataclass
from typing import Literal

from app.verification.bounds import VerificationBounds
from app.verification.errors import RejectedInputError

TokenKind = Literal["num", "var", "op", "lparen", "rparen", "eq"]

_TYPOGRAPHIC = {
    "\u2212": "-",  # minus sign
    "\u2013": "-",  # en dash
    "\u00d7": "*",  # multiplication sign
    "\u00b7": "*",  # middle dot
    "\u22c5": "*",  # dot operator
    "\u00f7": "/",  # division sign
}
_OPERATORS = frozenset("+-*/")
_WHITESPACE = frozenset(" \t")
_NON_FINITE_NAMES = frozenset({"inf", "infinity", "nan", "oo"})
_INEQUALITY = frozenset("<>\u2264\u2265\u2260!")
_NON_FINITE_SYMBOLS = frozenset("\u221e")


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    position: int


def _normalize(text: str) -> str:
    return "".join(_TYPOGRAPHIC.get(ch, ch) for ch in text)


def tokenize(raw: str, bounds: VerificationBounds, *, allow_powers: bool = False) -> list[Token]:
    if len(raw) > bounds.max_chars:
        raise RejectedInputError(
            "excessive", "too_long", f"more than {bounds.max_chars} characters"
        )
    text = _normalize(raw)
    if not text.strip():
        raise RejectedInputError("malformed", "empty", "nothing to check")

    tokens: list[Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _WHITESPACE:
            i += 1
            continue
        if ch.isascii() and ch.isdigit():
            i = _read_number(text, i, tokens, bounds)
        elif ch.isascii() and ch.isalpha():
            start = i
            while i < len(text) and text[i].isascii() and text[i].isalpha():
                i += 1
            _append_letters(text, start, i, tokens)
        elif ch in _OPERATORS:
            if ch == "*" and text[i + 1 : i + 2] == "*":
                raise RejectedInputError(
                    "unsupported", "exponent", "powers are outside this checker"
                )
            tokens.append(Token("op", ch, i))
            i += 1
        elif ch == "(":
            tokens.append(Token("lparen", ch, i))
            i += 1
        elif ch == ")":
            tokens.append(Token("rparen", ch, i))
            i += 1
        elif ch == "=":
            if text[i + 1 : i + 2] == "=":
                raise RejectedInputError("malformed", "malformed_equality", "use a single '='")
            tokens.append(Token("eq", ch, i))
            i += 1
        elif ch == "^":
            if allow_powers:
                tokens.append(Token("op", ch, i))
                i += 1
            else:
                raise RejectedInputError(
                    "unsupported", "exponent", "powers are outside this checker"
                )
        elif ch in _INEQUALITY:
            raise RejectedInputError("unsupported", "inequality", "only equations and expressions")
        elif ch in _NON_FINITE_SYMBOLS:
            raise RejectedInputError("unsupported", "non_finite", "infinity is not a number here")
        else:
            raise RejectedInputError(
                "malformed", "disallowed_character", f"character at {i} not allowed"
            )
        if len(tokens) > bounds.max_tokens:
            raise RejectedInputError(
                "excessive", "too_many_tokens", f"more than {bounds.max_tokens} tokens"
            )
    return tokens


def _read_number(text: str, i: int, tokens: list[Token], bounds: VerificationBounds) -> int:
    start = i
    while i < len(text) and text[i].isascii() and text[i].isdigit():
        i += 1
    integer_digits = i - start
    decimals = 0
    if i < len(text) and text[i] == ".":
        i += 1
        frac_start = i
        while i < len(text) and text[i].isascii() and text[i].isdigit():
            i += 1
        decimals = i - frac_start
        if decimals == 0:
            raise RejectedInputError(
                "malformed", "malformed_number", "a decimal point needs digits"
            )
    if integer_digits > bounds.max_integer_digits:
        raise RejectedInputError(
            "excessive", "number_too_large", f"more than {bounds.max_integer_digits} digits"
        )
    if decimals > bounds.max_decimal_places:
        raise RejectedInputError(
            "excessive",
            "too_many_decimal_places",
            f"more than {bounds.max_decimal_places} decimal places",
        )
    if i < len(text) and text[i] == ".":
        raise RejectedInputError("malformed", "malformed_number", "a number has one decimal point")
    tokens.append(Token("num", text[start:i], start))
    return i


def _append_letters(text: str, start: int, end: int, tokens: list[Token]) -> None:
    word = text[start:end]
    if len(word) == 1:
        tokens.append(Token("var", word, start))
        return
    # Multi-letter words are never split into implicit products: "sin(x)" or "os" would
    # otherwise silently become s*i*n*x or o*s.
    lowered = word.lower()
    if lowered in _NON_FINITE_NAMES:
        raise RejectedInputError("unsupported", "non_finite", "infinity/NaN is not a number here")
    following = text[end:].lstrip(" \t")
    if following.startswith("("):
        raise RejectedInputError(
            "unsupported", "unsupported_function", "functions are not supported"
        )
    raise RejectedInputError(
        "unsupported", "unsupported_identifier", "use single-letter variables like x"
    )
