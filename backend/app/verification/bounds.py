"""Explicit size and complexity limits applied before any SymPy object is constructed.

Every limit is checked on the raw text, token stream or our own syntax tree, so SymPy only
ever sees small linear expressions. This is the bounded execution policy: the work SymPy does
(expansion of a degree-one polynomial with at most ``max_nodes`` leaves) is cheap by
construction, so no thread timeout or subprocess sandbox is needed.
"""

from dataclasses import dataclass

BOUNDS_VERSION = "verification-bounds.v1"


@dataclass(frozen=True, slots=True)
class VerificationBounds:
    max_chars: int = 120
    max_tokens: int = 60
    max_nodes: int = 60
    max_depth: int = 10
    max_operations: int = 24
    max_integer_digits: int = 6
    max_decimal_places: int = 4
    # Applies to every exact rational the parser derives (constants and final coefficients).
    max_coefficient_digits: int = 18
    max_variables: int = 2
    version: str = BOUNDS_VERSION


DEFAULT_BOUNDS = VerificationBounds()
