"""Contracts for runtime-generated explanations that render as native manipulatives.

An ``ExplanationSpec`` is *data*: a closed vocabulary of bounded components (grouping and
distribution) with integer ranges and short plain text. The app renders it with its own
native components. There is no field that can carry script, markup, a URL or a component
name the app does not already ship, so a generated candidate can never execute anything.
"""

import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from app.schemas.common import ContractModel, UtcDatetime

MIN_FACTOR = 1
MAX_FACTOR = 12
MAX_SPEC_JSON_CHARS = 2_000

ExplanationConcept = Literal["concept.distribution", "concept.grouping"]
ComponentKind = Literal["grouping", "distribution"]

# Anything that could be read as markup, script, a link or a template placeholder.
_FORBIDDEN_TEXT = re.compile(
    r"[<>{}\[\]\\`$|]|[\x00-\x1f\x7f]|://|(?i:javascript:|data:|www\.|https?|file:|\.com\b)"
)


def plain_text(value: str) -> str:
    stripped = value.strip()
    if stripped != value or _FORBIDDEN_TEXT.search(value):
        raise ValueError("text must be plain words without markup, links or control characters")
    return value


PlainText = Annotated[str, AfterValidator(plain_text)]
Title = Annotated[PlainText, Field(min_length=1, max_length=80)]
Prompt = Annotated[PlainText, Field(min_length=1, max_length=160)]
Caption = Annotated[PlainText, Field(min_length=1, max_length=240)]
ItemLabel = Annotated[PlainText, Field(min_length=1, max_length=24)]
Factor = Annotated[int, Field(ge=MIN_FACTOR, le=MAX_FACTOR)]
NoteText = Annotated[str, Field(max_length=200)]


class IntRange(ContractModel):
    """The values a learner can pick for one quantity."""

    min: Factor
    max: Factor
    initial: Factor

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.min <= self.initial <= self.max:
            raise ValueError("initial must lie within min..max")
        return self


class GroupingSpec(ContractModel):
    """``groups`` equal groups of ``per_group`` items: the total is their product."""

    component: Literal["grouping"]
    groups: IntRange
    per_group: IntRange
    item_label: ItemLabel


class DistributionSpec(ContractModel):
    """``outer`` x (``left`` + ``right``) split into two rectangles of the same height."""

    component: Literal["distribution"]
    outer: IntRange
    left: IntRange
    right: IntRange


Manipulative = Annotated[GroupingSpec | DistributionSpec, Field(discriminator="component")]


class ExplanationSpec(ContractModel):
    schema_version: Literal["explanation-spec.v1"] = "explanation-spec.v1"
    concept_id: ExplanationConcept
    title: Title
    prompt: Prompt
    caption: Caption
    manipulative: Manipulative


class GeneratedExplanation(ContractModel):
    """What the Droid runtime is asked to return.

    ``self_check_notes`` is the model's own commentary. It is kept for the record and is
    never read by the release gate: a generated candidate cannot vouch for itself.
    """

    spec: ExplanationSpec
    self_check_notes: Annotated[list[NoteText], Field(max_length=5)] = Field(default_factory=list)


class ExplanationRequest(ContractModel):
    """Bounded learner-safe input: a concept, a misconception label and a short note.

    No learner id, name, raw media, history or secret is part of this contract.
    """

    schema_version: Literal["explanation-request.v1"] = "explanation-request.v1"
    concept_id: ExplanationConcept
    misconception: Annotated[str, Field(min_length=1, max_length=160)]
    context_note: Annotated[str, Field(max_length=400)] = ""
    preferred_component: ComponentKind | None = None


class CheckOutcome(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    passed: bool
    detail: Annotated[str, Field(max_length=200)] = ""


class TrustedCheckReport(ContractModel):
    """The result of the repository-owned checks for exactly one spec digest."""

    schema_version: Literal["trusted-check-result.v1"] = "trusted-check-result.v1"
    spec_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    passed: bool
    checks: Annotated[list[CheckOutcome], Field(min_length=1, max_length=20)]


ReleaseSource = Literal["generated_verified", "prevetted_fallback"]

FallbackReason = Literal[
    "integration_disabled",
    "not_configured",
    "generation_failed",
    "generation_timeout",
    "generation_cancelled",
    "invalid_candidate",
    "oversize_candidate",
    "cost_exceeded",
    "cost_unverified",
    "invariant_failed",
    "checks_unavailable",
    "checks_failed",
    "checks_timeout",
    "checks_malformed",
    "cleanup_failed",
]

IntegrationState = Literal["disabled", "not_configured", "configured_unverified"]


class ReleasedExplanation(ContractModel):
    """The only thing the learner-facing app may show: a labeled, trusted spec."""

    schema_version: Literal["released-explanation.v1"] = "released-explanation.v1"
    source: ReleaseSource
    # Visible text. The fallback label states that nothing was generated for this learner.
    label: Annotated[str, Field(min_length=1, max_length=160)]
    spec: ExplanationSpec
    spec_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    fallback_reason: FallbackReason | None = None
    factory_state: IntegrationState
    daytona_state: IntegrationState
    checks: list[CheckOutcome] = Field(default_factory=list)
    # Sandboxes this attempt created and the subset confirmed deleted, by exact ID.
    sandbox_ids_created: list[str] = Field(default_factory=list)
    sandbox_ids_deleted: list[str] = Field(default_factory=list)
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _source_matches_reason(self) -> Self:
        if (self.source == "prevetted_fallback") != (self.fallback_reason is not None):
            raise ValueError("a fallback names its reason; a verified release has none")
        if self.source == "generated_verified" and sorted(self.sandbox_ids_created) != sorted(
            self.sandbox_ids_deleted
        ):
            raise ValueError("a verified release needs every created sandbox confirmed deleted")
        return self
