"""Runtime ExplanationSpec generation through the installed Factory Droid CLI (droid-sdk).

This is the product's own runtime use of Droid, separate from using Droid to build the repo.
The adapter starts the configured ``droid exec`` subprocess through ``droid_sdk.Session`` with
no tools, rejected permission requests, an empty temporary working directory, a scrubbed
environment, one deadline, a bounded prompt and a bounded structured reply. Neither the SDK
nor ``droid exec`` offers a spending cap, so cost is only watched, not capped: the run is
interrupted once a reported credit total passes the limit, and a result that never reported
its credits is refused. The reply is only a *candidate*: ``pipeline.release_explanation``
decides whether it may ever be shown.

Constructing the adapter has no side effects; the subprocess starts inside ``generate``.
"""

import asyncio
import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from droid_sdk import (
    Autonomy,
    DroidError,
    Mode,
    ReasoningEffort,
    RunFailure,
    RunInterrupted,
    RunResult,
    RunSuccess,
    Runtime,
    RunTimeoutError,
    Session,
    SessionConfig,
    TokenUsageUpdate,
)

from app.config import Settings
from app.interactives.errors import InteractiveError
from app.redaction import redact_text, register_secrets
from app.schemas.interactives import (
    MAX_FACTOR,
    ExplanationRequest,
    GeneratedExplanation,
)

# Variables the Droid process needs to find its own login and certificates. Every other
# inherited variable is blanked, because the SDK merges the parent environment into the child.
ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TZ",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "https_proxy",
        "http_proxy",
        "no_proxy",
        "FACTORY_API_KEY",
    }
)

SYSTEM_PROMPT = (
    "You write one small interactive math explanation for a tutoring app. You have no tools "
    "and must not run commands, read files or browse. Reply with exactly one JSON object "
    "that matches the supplied schema: a single bounded grouping or distribution "
    "manipulative with integer ranges from 1 to "
    f"{MAX_FACTOR}, and short plain-text words only (no markup, links, code or symbols like "
    "angle brackets). Do not include a learner's name or any identifier. self_check_notes is "
    "optional commentary and is never used to approve your work."
)

# Grace for the SDK to interrupt and terminate the Droid subprocess on every exit path.
_CLOSE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class FactoryRuntimeConfig:
    executable: Path
    model: str
    reasoning_effort: ReasoningEffort
    timeout_seconds: float
    max_prompt_chars: int
    max_output_chars: int
    max_credits: float
    api_key: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "FactoryRuntimeConfig":
        if not settings.factory_droid_executable or not settings.factory_model:
            raise InteractiveError("not_configured")
        key = settings.factory_api_key.get_secret_value() if settings.factory_api_key else None
        return cls(
            executable=Path(settings.factory_droid_executable),
            model=settings.factory_model,
            reasoning_effort=ReasoningEffort(settings.factory_reasoning_effort),
            timeout_seconds=settings.factory_timeout_seconds,
            max_prompt_chars=settings.factory_max_prompt_chars,
            max_output_chars=settings.factory_max_output_chars,
            max_credits=settings.factory_max_credits,
            api_key=key or None,
        )


@dataclass(frozen=True)
class GeneratedCandidate:
    generated: GeneratedExplanation
    factory_credits: float | None


def scrubbed_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Blank every inherited variable outside the allowlist (application secrets included)."""
    return {name: "" for name in environ if name not in ENVIRONMENT_ALLOWLIST}


def build_prompt(request: ExplanationRequest) -> str:
    """The only learner-derived text sent: concept, misconception label and a short note."""
    lines = [
        f"Concept: {request.concept_id}",
        f"Misconception to address: {redact_text(request.misconception)}",
    ]
    if request.context_note:
        lines.append(f"Context: {redact_text(request.context_note)}")
    if request.preferred_component is not None:
        lines.append(f"Preferred component: {request.preferred_component}")
    lines.append("Return the JSON object now.")
    return "\n".join(lines)


def _structured_size(result: RunResult[GeneratedExplanation]) -> int:
    raw = result.structured_output
    if raw is None:
        return len(result.text)
    return len(json.dumps(raw, default=str))


def candidate_from_result(
    result: RunResult[GeneratedExplanation], config: FactoryRuntimeConfig
) -> GeneratedCandidate:
    if isinstance(result, RunInterrupted):
        raise InteractiveError("generation_cancelled")
    if _structured_size(result) > config.max_output_chars:
        raise InteractiveError("oversize_candidate")
    if isinstance(result, RunFailure):
        if result.subtype == "error_structured_output":
            raise InteractiveError("invalid_candidate")
        raise InteractiveError("generation_failed")
    if not isinstance(result, RunSuccess) or result.output is None:
        raise InteractiveError("invalid_candidate")
    credits = result.usage.factory_credits if result.usage is not None else None
    # The CLI exposes no spending cap, so a candidate whose cost it never reported cannot be
    # shown to have stayed within the configured limit and is refused.
    if credits is None:
        raise InteractiveError("cost_unverified")
    if credits > config.max_credits:
        raise InteractiveError("cost_exceeded")
    return GeneratedCandidate(generated=result.output, factory_credits=credits)


class FactoryExplanationGenerator:
    def __init__(
        self, config: FactoryRuntimeConfig, *, environ: Mapping[str, str] | None = None
    ) -> None:
        self._config = config
        self._environ = environ
        register_secrets([config.api_key])

    @property
    def config(self) -> FactoryRuntimeConfig:
        return self._config

    def _session(self, workdir: Path) -> Session:
        environ = os.environ if self._environ is None else self._environ
        runtime = Runtime(executable=self._config.executable, env=scrubbed_environment(environ))
        session_config = SessionConfig(
            mode=Mode.AUTO,
            autonomy=Autonomy.OFF,
            system_prompt=SYSTEM_PROMPT,
            # An explicit empty set: no built-in, MCP or skill tool is available.
            restrict_tools=(),
            auto_reject_permission_requests=True,
            disable_builtin_skills=True,
            mcp_servers=(),
        )
        return Session(
            cwd=workdir,
            model=self._config.model,
            reasoning_effort=self._config.reasoning_effort,
            config=session_config,
            runtime=runtime,
            api_key=self._config.api_key,
        )

    async def _converse(self, session: Session, prompt: str) -> RunResult[GeneratedExplanation]:
        await session.open()
        # Partial messages are what make the SDK deliver running usage updates.
        stream = session.stream(
            prompt,
            output=GeneratedExplanation,
            timeout=self._config.timeout_seconds,
            include_partial_messages=True,
        )
        async with stream:
            async for event in stream:
                # The SDK reports running usage while the turn is in flight. Leaving the
                # block here interrupts the run; spend between two updates is not bounded.
                if (
                    isinstance(event, TokenUsageUpdate)
                    and event.factory_credits is not None
                    and event.factory_credits > self._config.max_credits
                ):
                    raise InteractiveError("cost_exceeded")
        result: RunResult[GeneratedExplanation] = stream.result
        return result

    async def generate(self, request: ExplanationRequest) -> GeneratedCandidate:
        prompt = build_prompt(request)
        if len(prompt) > self._config.max_prompt_chars:
            raise InteractiveError("generation_failed")
        workdir = Path(tempfile.mkdtemp(prefix="rubberducky-droid-"))
        session = self._session(workdir)
        try:
            # The stream enforces the deadline; this outer bound also covers a stuck startup.
            result = await asyncio.wait_for(
                self._converse(session, prompt), timeout=self._config.timeout_seconds + 5
            )
        except InteractiveError:
            raise
        except (TimeoutError, RunTimeoutError) as error:
            raise InteractiveError("generation_timeout") from error
        except (DroidError, OSError) as error:
            raise InteractiveError("generation_failed") from error
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    asyncio.shield(session.close()), timeout=_CLOSE_TIMEOUT_SECONDS
                )
            shutil.rmtree(workdir, ignore_errors=True)
        return candidate_from_result(result, self._config)
