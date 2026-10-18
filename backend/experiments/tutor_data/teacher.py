"""Configurable teacher generation. Disabled unless a caller activates it.

Generated rows stay unreviewed, so preparation will not put them in a training split until a
person reviews them. Remote providers also need ``allow_remote``; this module does not enable
network access by itself. The mock path records the existing mock provider's name and does
not call a live model.
"""

from collections.abc import Sequence
from typing import Protocol

from app.inference.providers import MOCK_LABEL
from experiments.tutor_data.contracts import SharedExample

REMOTE_PROVIDERS = frozenset({"transformers", "endpoint", "claude"})


class TeacherGenerationDisabledError(RuntimeError):
    """Teacher generation was not explicitly activated, or a remote provider was not allowed."""


class TeacherBudgetError(RuntimeError):
    """The call has no positive cost bound, or the estimate exceeds it."""


class TeacherTransport(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockTeacherTransport:
    """Deterministic offline wording identified as the mock provider."""

    def __init__(self) -> None:
        self.provider_name = MOCK_LABEL.name

    def complete(self, prompt: str) -> str:
        del prompt
        return "What part of the expression has not been used yet?"


def generate_teacher_examples(
    prompts: Sequence[str],
    *,
    transport: TeacherTransport,
    activated: bool = False,
    max_cost_usd: float | None = None,
    provider: str = "mock",
    allow_remote: bool = False,
    model_id: str = "mock-teacher",
    model_version: str = "mock.v1",
    template_id: str = "tutor-move.v1",
    cost_per_example: float = 0.01,
    source: str = "rubberducky.teacher",
    terms: str = "Teacher-generated fictional examples. Not student work.",
    license_name: str = "CC0-1.0",
) -> list[SharedExample]:
    if not activated:
        raise TeacherGenerationDisabledError(
            "teacher generation is disabled; pass activated=True to enable it"
        )
    if provider in REMOTE_PROVIDERS and not allow_remote:
        raise TeacherGenerationDisabledError(
            f"remote teacher provider {provider} is not activated"
        )
    if provider != "mock" and provider not in REMOTE_PROVIDERS:
        raise TeacherGenerationDisabledError(f"unknown teacher provider {provider}")
    if max_cost_usd is None or max_cost_usd <= 0:
        raise TeacherBudgetError("a positive max_cost_usd bound is required before generation")
    estimated = cost_per_example * len(prompts)
    if estimated > max_cost_usd:
        raise TeacherBudgetError(f"estimated cost {estimated} exceeds bound {max_cost_usd}")
    examples: list[SharedExample] = []
    for index, prompt in enumerate(prompts):
        completion = transport.complete(prompt)
        examples.append(
            SharedExample(
                example_id=f"ex.teacher.{index}",
                source=source,
                terms=terms,
                license=license_name,
                review_status="unreviewed",
                reviewer=None,
                scenario_family="scenario.teacher",
                problem_family=f"problem.teacher.{index}",
                concept_family="concept.teacher",
                prompt=prompt,
                completion=completion,
                provenance="teacher_generated",
                provider=provider,
                model_id=model_id,
                model_version=model_version,
                template_id=template_id,
                cost_usd=cost_per_example,
                forbidden_disclosure=None,
            )
        )
    return examples
