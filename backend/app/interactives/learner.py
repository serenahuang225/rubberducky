"""Learner-facing explanation that never starts Factory or Daytona.

The release gate in ``pipeline.py`` is unchanged. This path does not construct a generator or
a checker, so it cannot pay for a run or create a sandbox. It returns the repository's
pre-vetted spec with the real disabled / not-configured / configured-unverified states.
"""

from app.clock import utc_now
from app.config import Settings
from app.interactives import trusted_checks
from app.interactives.fallback import FALLBACK_LABEL, prevetted_spec_for
from app.interactives.status import (
    InteractiveIntegrationStatus,
    describe_interactive_integrations,
)
from app.schemas.interactives import (
    ExplanationRequest,
    FallbackReason,
    LearnerExplanation,
    ReleasedExplanation,
)

LEARNER_NOTICE = (
    "Factory and Daytona were not contacted. "
    "This is the app's pre-vetted explanation, not a generated release."
)


def _fallback_reason(status: InteractiveIntegrationStatus) -> FallbackReason:
    """Match the offline branches of ``ReleasePipeline.release`` without calling them.

    A configured Factory is not started from this path, including when Daytona is also
    configured. That case stays a fallback (``checks_unavailable``) rather than a verified
    release.
    """
    if status.factory.state == "disabled":
        return "integration_disabled"
    if status.factory.state == "not_configured":
        return "not_configured"
    return "checks_unavailable"


def release_for_learner(settings: Settings, request: ExplanationRequest) -> LearnerExplanation:
    status = describe_interactive_integrations(settings)
    spec = prevetted_spec_for(request)
    released = ReleasedExplanation(
        source="prevetted_fallback",
        label=FALLBACK_LABEL,
        spec=spec,
        spec_digest=trusted_checks.canonical_digest(spec.model_dump(mode="json")),
        fallback_reason=_fallback_reason(status),
        factory_state=status.factory.state,
        daytona_state=status.daytona.state,
        checks=[],
        sandbox_ids_created=[],
        sandbox_ids_deleted=[],
        created_at=utc_now(),
    )
    return LearnerExplanation(notice=LEARNER_NOTICE, release=released)
