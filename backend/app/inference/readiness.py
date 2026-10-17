"""Model readiness, reported separately from application health.

This module only inspects configuration and the state of an adapter that already exists.
It must never import model libraries, download weights or contact a provider, so health
checks stay cheap and side-effect free.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

from app.config import ProviderName, Settings
from app.inference.factory import peek_adapter
from app.inference.local import LocalTransformersAdapter

ReadinessState = Literal["ready", "not_loaded", "disabled", "unverified"]


class ModelReadiness(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["model-readiness.v1"] = "model-readiness.v1"
    provider: ProviderName
    state: ReadinessState
    ready: bool
    is_mock: bool
    label: str
    model_id: str | None
    model_revision: str | None
    detail: str
    # Where the learner's context goes when this provider is used; None for the mock.
    transmission: str | None = None
    # Stable code of the most recent failed load, if any (never provider text).
    last_error_code: str | None = None


def describe_model_readiness(settings: Settings) -> ModelReadiness:
    provider = settings.tutor_provider
    if provider == "mock":
        return ModelReadiness(
            provider=provider,
            state="ready",
            ready=True,
            is_mock=True,
            label="Deterministic mock tutor (not a language model)",
            model_id=None,
            model_revision=None,
            detail="Scripted responses for development and tests.",
        )
    if provider == "transformers":
        return _local_readiness(settings)
    return _remote_readiness(settings)


def _local_readiness(settings: Settings) -> ModelReadiness:
    common = {
        "provider": "transformers",
        "is_mock": False,
        "model_id": settings.tutor_local_model_id,
        "model_revision": settings.tutor_local_model_revision,
        "transmission": "this_process",
    }
    if not settings.tutor_local_model_load_enabled:
        return ModelReadiness(
            **common,  # type: ignore[arg-type]
            state="disabled",
            ready=False,
            label="Local Transformers model (disabled)",
            detail=(
                "Local model loading is opt-in; set TUTOR_LOCAL_MODEL_LOAD_ENABLED=true. "
                "Nothing is downloaded at startup."
            ),
        )
    where = f"{settings.tutor_local_device}/{settings.tutor_local_dtype}"
    adapter = peek_adapter(settings)
    if isinstance(adapter, LocalTransformersAdapter):
        if adapter.load_state == "loaded":
            return ModelReadiness(
                **common,  # type: ignore[arg-type]
                state="ready",
                ready=True,
                label=f"Local Transformers model (loaded, {where})",
                detail="The model is loaded in this process and reused for every turn.",
            )
        if adapter.load_state == "failed":
            return ModelReadiness(
                **common,  # type: ignore[arg-type]
                state="not_loaded",
                ready=False,
                label="Local Transformers model (load failed)",
                detail="The last load attempt failed; the next turn retries it.",
                last_error_code=adapter.last_load_failure,
            )
    return ModelReadiness(
        **common,  # type: ignore[arg-type]
        state="not_loaded",
        ready=False,
        label=f"Local Transformers model (not loaded, {where})",
        detail="The model loads lazily on first use, never at startup.",
    )


def _remote_readiness(settings: Settings) -> ModelReadiness:
    provider = settings.tutor_provider
    if provider == "claude":
        label, model = "Claude", settings.anthropic_model
        missing = [
            name
            for name, present in (
                ("ANTHROPIC_API_KEY", _has_key(settings.anthropic_api_key)),
                ("ANTHROPIC_MODEL", bool(model)),
            )
            if not present
        ]
    else:
        label, model = "OpenAI-compatible endpoint", settings.tutor_endpoint_model
        missing = [
            name
            for name, present in (
                ("TUTOR_ENDPOINT_BASE_URL", bool(settings.tutor_endpoint_base_url)),
                ("TUTOR_ENDPOINT_MODEL", bool(model)),
            )
            if not present
        ]
    common = {
        "provider": provider,
        "is_mock": False,
        "model_id": model,
        "model_revision": None,
        "transmission": "remote_provider",
        "ready": False,
    }
    if not settings.external_integrations_enabled:
        return ModelReadiness(
            **common,  # type: ignore[arg-type]
            state="disabled",
            label=f"{label} (disabled)",
            detail="Remote providers require EXTERNAL_INTEGRATIONS_ENABLED=true.",
        )
    if missing:
        return ModelReadiness(
            **common,  # type: ignore[arg-type]
            state="unverified",
            label=f"{label} (not configured)",
            detail="Missing configuration: " + ", ".join(missing) + ". Turns will be refused.",
        )
    return ModelReadiness(
        **common,  # type: ignore[arg-type]
        state="unverified",
        label=f"{label} (configured, unverified)",
        detail=(
            "The provider is not contacted at startup, so its readiness is unverified. "
            "Turn context is sent to it when used."
        ),
    )


def _has_key(key: SecretStr | None) -> bool:
    return key is not None and bool(key.get_secret_value())
