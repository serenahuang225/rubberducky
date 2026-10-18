"""The release gate: only a trusted, tested candidate may reach a learner.

Order of events for one request:

1. If either integration is not usable, return the labeled pre-vetted fallback *before*
   calling Factory, so a candidate that could never be checked is never generated or paid for.
2. Ask the Droid runtime for a candidate (data only).
3. Run the repository's trusted checks locally, then in a private Daytona sandbox, and accept
   only a passing report for exactly this candidate's digest.
4. Anything else (any adapter failure, timeout, oversize, failed or malformed check) returns
   the labeled fallback with a stable reason. Cancellation is not a fallback: it propagates
   after each adapter has cleaned up what it started.

The candidate's own ``self_check_notes`` are never read here.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.clock import utc_now
from app.config import Settings
from app.interactives import trusted_checks
from app.interactives.daytona_checks import (
    ClientFactory,
    DaytonaCheckConfig,
    DaytonaTrustedChecker,
    SandboxCheckError,
    SandboxCheckResult,
    default_client_factory,
    verify_report,
)
from app.interactives.errors import InteractiveError
from app.interactives.factory_runtime import (
    FactoryExplanationGenerator,
    FactoryRuntimeConfig,
    GeneratedCandidate,
)
from app.interactives.fallback import FALLBACK_LABEL, GENERATED_LABEL, prevetted_spec_for
from app.interactives.status import describe_interactive_integrations
from app.schemas.interactives import (
    CheckOutcome,
    ExplanationRequest,
    ExplanationSpec,
    FallbackReason,
    IntegrationState,
    ReleasedExplanation,
)


class ExplanationGenerator(Protocol):
    async def generate(self, request: ExplanationRequest) -> GeneratedCandidate: ...


class SpecChecker(Protocol):
    async def check(self, spec: ExplanationSpec) -> SandboxCheckResult: ...


@dataclass(frozen=True)
class ReleasePipeline:
    generator: ExplanationGenerator | None
    checker: SpecChecker | None
    factory_state: IntegrationState
    daytona_state: IntegrationState
    clock: Callable[[], datetime] = utc_now

    def _fallback(
        self,
        request: ExplanationRequest,
        reason: FallbackReason,
        *,
        checks: list[CheckOutcome] | None = None,
        created: tuple[str, ...] = (),
        deleted: tuple[str, ...] = (),
    ) -> ReleasedExplanation:
        spec = prevetted_spec_for(request)
        return ReleasedExplanation(
            source="prevetted_fallback",
            label=FALLBACK_LABEL,
            spec=spec,
            spec_digest=trusted_checks.canonical_digest(spec.model_dump(mode="json")),
            fallback_reason=reason,
            factory_state=self.factory_state,
            daytona_state=self.daytona_state,
            checks=checks or [],
            sandbox_ids_created=list(created),
            sandbox_ids_deleted=list(deleted),
            created_at=self.clock(),
        )

    async def release(self, request: ExplanationRequest) -> ReleasedExplanation:
        if self.generator is None:
            reason: FallbackReason = (
                "integration_disabled" if self.factory_state == "disabled" else "not_configured"
            )
            return self._fallback(request, reason)
        if self.checker is None:
            return self._fallback(request, "checks_unavailable")
        try:
            candidate = await self.generator.generate(request)
        except InteractiveError as error:
            return self._fallback(request, error.code)

        spec = candidate.generated.spec
        spec_data = spec.model_dump(mode="json")
        local = trusted_checks.check_spec(spec_data)
        local_checks = [CheckOutcome.model_validate(item) for item in local["checks"]]
        if not local["passed"]:
            return self._fallback(request, "invariant_failed", checks=local_checks)

        try:
            result = await self.checker.check(spec)
        except SandboxCheckError as error:
            return self._fallback(request, error.code, created=error.created, deleted=error.deleted)
        except InteractiveError as error:
            return self._fallback(request, error.code)

        digest = trusted_checks.canonical_digest(spec_data)
        try:
            report = verify_report(result.report, expected_digest=digest)
        except InteractiveError as error:
            return self._fallback(
                request,
                error.code,
                created=result.sandbox_ids_created,
                deleted=result.sandbox_ids_deleted,
            )
        if not report.passed:
            return self._fallback(
                request,
                "checks_failed",
                checks=report.checks,
                created=result.sandbox_ids_created,
                deleted=result.sandbox_ids_deleted,
            )
        return ReleasedExplanation(
            source="generated_verified",
            label=GENERATED_LABEL,
            spec=spec,
            spec_digest=digest,
            factory_state=self.factory_state,
            daytona_state=self.daytona_state,
            checks=report.checks,
            sandbox_ids_created=list(result.sandbox_ids_created),
            sandbox_ids_deleted=list(result.sandbox_ids_deleted),
            created_at=self.clock(),
        )


def pipeline_from_settings(
    settings: Settings, *, client_factory: ClientFactory = default_client_factory
) -> ReleasePipeline:
    """Build adapters only for integrations that are explicitly enabled and configured.

    Building an adapter starts nothing; a subprocess or sandbox exists only inside ``release``.
    Factory is skipped whenever Daytona could not check its candidate.
    """
    status = describe_interactive_integrations(settings)
    generator: FactoryExplanationGenerator | None = None
    checker: DaytonaTrustedChecker | None = None
    if status.daytona.state == "configured_unverified":
        checker = DaytonaTrustedChecker(
            DaytonaCheckConfig.from_settings(settings), client_factory=client_factory
        )
    if status.factory.state == "configured_unverified":
        generator = FactoryExplanationGenerator(FactoryRuntimeConfig.from_settings(settings))
    return ReleasePipeline(
        generator=generator,
        checker=checker,
        factory_state=status.factory.state,
        daytona_state=status.daytona.state,
    )
