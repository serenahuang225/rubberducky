"""Helpers that build specs the contract would refuse, to prove the later gates still hold."""

from typing import Any

from app.schemas.interactives import (
    DistributionSpec,
    ExplanationSpec,
    GroupingSpec,
    IntRange,
)


def unvalidated_spec(
    base: ExplanationSpec, *, manipulative: dict[str, Any] | None = None, **top: Any
) -> ExplanationSpec:
    """A spec skipping Pydantic validation, as a buggy or malicious generator could emit."""
    inner = base.manipulative.model_dump(mode="json")
    inner.update(manipulative or {})
    for name, value in inner.items():
        if isinstance(value, dict):
            inner[name] = IntRange.model_construct(**value)
    kind = GroupingSpec if inner["component"] == "grouping" else DistributionSpec
    data = {**base.model_dump(mode="json"), **top}
    return ExplanationSpec.model_construct(
        **{**data, "manipulative": kind.model_construct(**inner)}
    )
