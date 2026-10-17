"""Inspectable specifications of the initial unit's problems.

The database ``problems`` rows are the durable curriculum records (and foreign-key targets).
These specs add what the deterministic policy needs: the expected solution, the completed
distribution step (which a first hint must not disclose), the known partial-distribution
error forms and the deterministic board layout of the statement.
"""

from dataclasses import dataclass, field
from typing import Literal

import sympy

from app.db.seed import (
    EXPLANATION_PROBLEM_ID,
    FIXTURE_PROBLEM_ID,
    STRUCTURAL_TRANSFER_PROBLEM_ID,
    TRANSFER_PROBLEM_ID,
)
from app.verification import assess_input
from app.verification.parser import ParsedEquation

ProblemKind = Literal["practice", "transfer", "explanation"]

DISTRIBUTION = "concept.distribution"
LINEAR_EQUATIONS = "concept.linear_equations"

# Deterministic board layout for a problem statement (logical board units).
STATEMENT_X = 80.0
STATEMENT_Y = 120.0
STATEMENT_CHAR_WIDTH = 26.0
GROUP_MARK_OFFSET = 18.0


@dataclass(frozen=True)
class ProblemSpec:
    problem_id: str
    statement: str
    kind: ProblemKind
    concept_id: str
    # Concept that individual rewriting steps provide evidence about.
    step_concept_id: str
    variable: str | None = None
    solution: str | None = None
    group_text: str | None = None
    factor_text: str | None = None
    expanded_step: str | None = None
    # The rewritten side alone (e.g. "2x + 6"); showing it would also complete the step.
    expanded_side: str | None = None
    partial_distribution_steps: tuple[str, ...] = field(default_factory=tuple)
    rubric_id: str | None = None

    def solution_claims(self) -> tuple[str, ...]:
        if self.variable is None or self.solution is None:
            return ()
        return (f"{self.variable} = {self.solution}", f"{self.solution} = {self.variable}")

    def group_span(self) -> tuple[float, float] | None:
        """Board x-range under the parenthesized group, from the fixed statement layout."""
        if self.group_text is None:
            return None
        start = self.statement.find(self.group_text)
        if start < 0:
            return None
        end = start + len(self.group_text)
        return (
            STATEMENT_X + start * STATEMENT_CHAR_WIDTH,
            STATEMENT_X + end * STATEMENT_CHAR_WIDTH,
        )


PROBLEMS: dict[str, ProblemSpec] = {
    spec.problem_id: spec
    for spec in (
        ProblemSpec(
            problem_id=FIXTURE_PROBLEM_ID,
            statement="2(x + 3) = 14",
            kind="practice",
            concept_id=LINEAR_EQUATIONS,
            step_concept_id=DISTRIBUTION,
            variable="x",
            solution="4",
            group_text="(x + 3)",
            factor_text="2",
            expanded_step="2x + 6 = 14",
            expanded_side="2x + 6",
            partial_distribution_steps=("2x + 3 = 14",),
        ),
        ProblemSpec(
            problem_id=TRANSFER_PROBLEM_ID,
            statement="3(x - 2) = 12",
            kind="transfer",
            concept_id=LINEAR_EQUATIONS,
            step_concept_id=DISTRIBUTION,
            variable="x",
            solution="6",
            group_text="(x - 2)",
            factor_text="3",
            expanded_step="3x - 6 = 12",
            expanded_side="3x - 6",
            partial_distribution_steps=("3x - 2 = 12",),
        ),
        ProblemSpec(
            problem_id=STRUCTURAL_TRANSFER_PROBLEM_ID,
            statement="5 = 2(z - 3) + 1",
            kind="transfer",
            concept_id=LINEAR_EQUATIONS,
            step_concept_id=DISTRIBUTION,
            variable="z",
            solution="5",
            group_text="(z - 3)",
            factor_text="2",
            expanded_step="5 = 2z - 6 + 1",
            expanded_side="2z - 6",
            partial_distribution_steps=("5 = 2z - 3 + 1",),
        ),
        ProblemSpec(
            problem_id=EXPLANATION_PROBLEM_ID,
            statement="Explain why 2(x + 3) equals 2x + 6.",
            kind="explanation",
            concept_id=DISTRIBUTION,
            step_concept_id=DISTRIBUTION,
            rubric_id="rubric.distribution.explain",
        ),
    )
}

TRANSFER_ORDER: tuple[str, ...] = (TRANSFER_PROBLEM_ID, STRUCTURAL_TRANSFER_PROBLEM_ID)


class UnknownProblemError(LookupError):
    pass


def problem_spec(problem_id: str) -> ProblemSpec:
    try:
        return PROBLEMS[problem_id]
    except KeyError as error:
        raise UnknownProblemError(problem_id) from error


def _signature(statement: str) -> tuple[str, str] | None:
    assessment, parsed = assess_input(statement)
    if assessment.status != "parsed" or not isinstance(parsed, ParsedEquation):
        return None
    placeholder = sympy.Symbol("v")
    replacements = {sympy.Symbol(name): placeholder for name in parsed.variables}
    left = sympy.expand(parsed.left.subs(replacements))
    right = sympy.expand(parsed.right.subs(replacements))
    return str(sympy.sstr(left)), str(sympy.sstr(right))


def fresh_variant_reason(original: ProblemSpec, candidate: ProblemSpec) -> str | None:
    """Why ``candidate`` is NOT a fresh transfer of ``original`` (``None`` when it is).

    A fresh opportunity must change numbers or form. The same problem, or one that only
    renames the variable, is not fresh.
    """
    if candidate.problem_id == original.problem_id:
        return "same_problem"
    if candidate.kind != "transfer":
        return "not_a_transfer_problem"
    first, second = _signature(original.statement), _signature(candidate.statement)
    if first is None or second is None:
        return "not_checkable"
    if first == second:
        return "renamed_only"
    return None
