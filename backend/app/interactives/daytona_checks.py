"""Trusted candidate checks in a private, ephemeral Daytona sandbox (async Daytona SDK).

The repository-owned ``trusted_checks.py`` is uploaded verbatim together with the candidate
spec and run once. The candidate contributes data only: it can neither bring nor replace a
check. Every sandbox this attempt created is deleted by its exact ID on every exit path
(pass, failed checks, malformed output, creation error, timeout, cancellation). When the
create call fails before an ID is known, the sandboxes carrying this attempt's unique run
label are found and deleted by their exact IDs; nothing else is ever touched.

Nothing here runs at import time. The SDK client is built inside ``check``, always with an
explicit key, validated https ``daytona.io`` URL and target so the SDK never falls back to
process environment or dotenv files for credentials or the endpoint.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.config import Settings
from app.interactives import trusted_checks
from app.interactives.endpoints import validate_daytona_api_url
from app.interactives.errors import InteractiveError
from app.redaction import register_secrets
from app.schemas.interactives import (
    MAX_SPEC_JSON_CHARS,
    ExplanationSpec,
    FallbackReason,
    TrustedCheckReport,
)

RUN_LABEL = "rubberducky_check_run"
SCRIPT_NAME = "trusted_checks.py"
SPEC_NAME = "candidate_spec.json"
COMMAND = f"python3 {SCRIPT_NAME} {SPEC_NAME}"
MAX_REPORT_CHARS = 8_000
# Sandbox lifetime backstops if an explicit delete were ever lost: auto-stop then delete.
SANDBOX_TTL_MINUTES = 10
_UPLOAD_ALLOWANCE_SECONDS = 15.0


class DaytonaClientLike(Protocol):
    """The slice of ``daytona.AsyncDaytona`` the adapter uses (signatures are checked in tests)."""

    async def create(self, params: Any = None, *, timeout: float = 60) -> Any: ...

    async def delete(self, sandbox: Any, timeout: float = 60, wait: bool = False) -> None: ...

    def list(
        self, query: Any = None, request_timeout: float | None = None
    ) -> AsyncIterator[Any]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class DaytonaCheckConfig:
    api_key: str
    api_url: str
    target: str
    create_timeout_seconds: float
    exec_timeout_seconds: int
    cleanup_timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "DaytonaCheckConfig":
        key = settings.daytona_api_key.get_secret_value() if settings.daytona_api_key else ""
        if not key:
            raise InteractiveError("not_configured")
        try:
            validate_daytona_api_url(settings.daytona_api_url)
        except ValueError as error:
            raise InteractiveError("not_configured") from error
        return cls(
            api_key=key,
            api_url=settings.daytona_api_url,
            target=settings.daytona_target,
            create_timeout_seconds=settings.daytona_create_timeout_seconds,
            exec_timeout_seconds=settings.daytona_exec_timeout_seconds,
            cleanup_timeout_seconds=settings.daytona_cleanup_timeout_seconds,
        )


@dataclass(frozen=True)
class SandboxCheckResult:
    report: TrustedCheckReport
    sandbox_ids_created: tuple[str, ...]
    sandbox_ids_deleted: tuple[str, ...]


class SandboxCheckError(InteractiveError):
    """A failed attempt, with the exact sandbox IDs it created and managed to delete."""

    def __init__(
        self,
        code: FallbackReason,
        *,
        created: tuple[str, ...] = (),
        deleted: tuple[str, ...] = (),
    ) -> None:
        super().__init__(code)
        self.created = created
        self.deleted = deleted


ClientFactory = Callable[[DaytonaCheckConfig], DaytonaClientLike]


def default_client_factory(config: DaytonaCheckConfig) -> DaytonaClientLike:
    validate_daytona_api_url(config.api_url)
    from daytona import AsyncDaytona, DaytonaConfig

    client: DaytonaClientLike = AsyncDaytona(
        DaytonaConfig(api_key=config.api_key, api_url=config.api_url, target=config.target)
    )
    return client


def canonical_spec_json(spec: ExplanationSpec) -> str:
    return json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def verify_report(report: TrustedCheckReport, *, expected_digest: str) -> TrustedCheckReport:
    """Accept only a self-consistent report for exactly this candidate's digest."""
    names = tuple(check.name for check in report.checks)
    if (
        report.spec_digest != expected_digest
        or names != trusted_checks.CHECK_NAMES
        or report.passed != all(check.passed for check in report.checks)
    ):
        raise InteractiveError("checks_malformed")
    return report


def parse_report(output: str | None) -> TrustedCheckReport:
    text = (output or "").strip()
    if not text or len(text) > MAX_REPORT_CHARS:
        raise InteractiveError("checks_malformed")
    last_line = text.splitlines()[-1]
    try:
        return TrustedCheckReport.model_validate_json(last_line)
    except ValidationError as error:
        raise InteractiveError("checks_malformed") from error


def _timeout_types() -> tuple[type[BaseException], ...]:
    import daytona

    return (
        TimeoutError,
        daytona.DaytonaTimeoutError,
        daytona.DaytonaProcessExecutionTimeoutError,
        daytona.DaytonaQueueTimeoutError,
        daytona.DaytonaConnectionTimeoutError,
    )


class DaytonaTrustedChecker:
    def __init__(
        self,
        config: DaytonaCheckConfig,
        *,
        client_factory: ClientFactory = default_client_factory,
        upload_allowance_seconds: float = _UPLOAD_ALLOWANCE_SECONDS,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._upload_allowance = upload_allowance_seconds
        register_secrets([config.api_key])

    async def check(self, spec: ExplanationSpec) -> SandboxCheckResult:
        payload = canonical_spec_json(spec)
        if len(payload) > MAX_SPEC_JSON_CHARS:
            raise SandboxCheckError("oversize_candidate")
        expected_digest = trusted_checks.canonical_digest(spec.model_dump(mode="json"))
        run_id = uuid.uuid4().hex
        created: list[str] = []
        handles: dict[str, Any] = {}
        failure: InteractiveError | None = None
        report: TrustedCheckReport | None = None
        try:
            client = self._client_factory(self._config)
        except Exception as error:
            raise SandboxCheckError("checks_unavailable") from error
        try:
            try:
                report = await self._run(client, run_id, payload, expected_digest, created, handles)
            except InteractiveError as error:
                failure = error
            except Exception as error:
                failure = InteractiveError(
                    "checks_timeout" if self._is_timeout(error) else "checks_unavailable"
                )
        finally:
            # Also reached on cancellation: delete before the cancellation propagates.
            deleted, cleanup_complete = await self._cleanup(client, run_id, created, handles)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    asyncio.shield(client.close()), timeout=self._config.cleanup_timeout_seconds
                )
        if not cleanup_complete:
            # Takes precedence over the check outcome: a sandbox may still exist and bill.
            raise SandboxCheckError(
                "cleanup_failed", created=tuple(created), deleted=tuple(deleted)
            )
        if failure is not None or report is None:
            code: FallbackReason = failure.code if failure is not None else "checks_unavailable"
            raise SandboxCheckError(code, created=tuple(created), deleted=tuple(deleted))
        return SandboxCheckResult(
            report=report, sandbox_ids_created=tuple(created), sandbox_ids_deleted=tuple(deleted)
        )

    @staticmethod
    def _is_timeout(error: BaseException) -> bool:
        try:
            return isinstance(error, _timeout_types())
        except ImportError:
            return isinstance(error, TimeoutError)

    async def _run(
        self,
        client: DaytonaClientLike,
        run_id: str,
        payload: str,
        expected_digest: str,
        created: list[str],
        handles: dict[str, Any],
    ) -> TrustedCheckReport:
        config = self._config
        total = config.create_timeout_seconds + self._upload_allowance + config.exec_timeout_seconds
        async with asyncio.timeout(total):
            sandbox = await client.create(
                self._create_params(run_id), timeout=config.create_timeout_seconds
            )
            created.append(str(sandbox.id))
            handles[str(sandbox.id)] = sandbox
            script = Path(trusted_checks.__file__).read_bytes()
            await sandbox.fs.upload_file(script, SCRIPT_NAME)
            await sandbox.fs.upload_file(payload.encode("ascii"), SPEC_NAME)
            response = await sandbox.process.exec(COMMAND, timeout=config.exec_timeout_seconds)
        report = parse_report(getattr(response, "result", None))
        # The script exits 0 exactly when every check passed; a report that disagrees with
        # the exit code was not produced by the uploaded script.
        if (getattr(response, "exit_code", None) == 0) != report.passed:
            raise InteractiveError("checks_malformed")
        return verify_report(report, expected_digest=expected_digest)

    @staticmethod
    def _create_params(run_id: str) -> Any:
        from daytona import CreateSandboxFromSnapshotParams

        return CreateSandboxFromSnapshotParams(
            language="python",
            labels={RUN_LABEL: run_id},
            public=False,
            ephemeral=True,
            auto_stop_interval=1,
            ttl_minutes=SANDBOX_TTL_MINUTES,
            queue_timeout=1,
            # Requested, not assumed: enforcement depends on the account tier.
            network_block_all=True,
        )

    async def _cleanup(
        self,
        client: DaytonaClientLike,
        run_id: str,
        created: list[str],
        handles: dict[str, Any],
    ) -> tuple[list[str], bool]:
        """Delete this attempt's sandboxes by exact ID.

        Returns the confirmed-deleted IDs and whether cleanup is known to be complete: a failed
        delete, or a failed label lookup that leaves a possible orphan unknown, is not.
        """
        seconds = self._config.cleanup_timeout_seconds
        complete = True
        if not created:
            # create() may have been interrupted after the service made the sandbox but before
            # we learned its ID: find it by this attempt's unique label, never by anything else.
            try:
                async with asyncio.timeout(seconds):
                    query = _label_query(run_id)
                    async for sandbox in client.list(query):
                        labels = getattr(sandbox, "labels", None) or {}
                        if labels.get(RUN_LABEL) == run_id and str(sandbox.id) not in handles:
                            created.append(str(sandbox.id))
                            handles[str(sandbox.id)] = sandbox
            except Exception:
                complete = False
        deleted: list[str] = []
        for sandbox_id in created:
            try:
                await asyncio.wait_for(
                    asyncio.shield(client.delete(handles[sandbox_id], timeout=seconds, wait=True)),
                    timeout=seconds + 5,
                )
            except Exception:
                complete = False
                continue
            deleted.append(sandbox_id)
        return deleted, complete


def _label_query(run_id: str) -> Any:
    from daytona import ListSandboxesQuery

    return ListSandboxesQuery(labels={RUN_LABEL: run_id})
