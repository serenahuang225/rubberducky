"""Pre-vetted explanations used whenever a generated candidate is unavailable or unproven.

These are repository-owned specs checked by the same trusted checks as any candidate (see
``tests/test_interactive_release.py``). They are always shown with a label saying they were
not generated for this learner.
"""

from app.schemas.interactives import (
    DistributionSpec,
    ExplanationRequest,
    ExplanationSpec,
    GroupingSpec,
    IntRange,
)

FALLBACK_LABEL = "Pre-vetted explanation from the app (not generated for you)"
GENERATED_LABEL = "Generated explanation that passed the app's own checks"

DISTRIBUTION_FALLBACK = ExplanationSpec(
    concept_id="concept.distribution",
    title="Share the outside number with both parts",
    prompt="Change the outside number. What happens to both rectangles?",
    caption="The big rectangle has the same area as the two smaller rectangles together.",
    manipulative=DistributionSpec(
        component="distribution",
        outer=IntRange(min=1, max=6, initial=3),
        left=IntRange(min=1, max=8, initial=4),
        right=IntRange(min=1, max=8, initial=2),
    ),
)

GROUPING_FALLBACK = ExplanationSpec(
    concept_id="concept.grouping",
    title="Equal groups make a total",
    prompt="Add a group. How does the total change?",
    caption="Every group holds the same number of counters, so the total is groups times counters.",
    manipulative=GroupingSpec(
        component="grouping",
        groups=IntRange(min=1, max=8, initial=3),
        per_group=IntRange(min=1, max=8, initial=4),
        item_label="counter",
    ),
)

PREVETTED_SPECS: dict[str, ExplanationSpec] = {
    "distribution": DISTRIBUTION_FALLBACK,
    "grouping": GROUPING_FALLBACK,
}


def prevetted_spec_for(request: ExplanationRequest) -> ExplanationSpec:
    if request.preferred_component is not None:
        return PREVETTED_SPECS[request.preferred_component]
    return GROUPING_FALLBACK if request.concept_id == "concept.grouping" else DISTRIBUTION_FALLBACK
