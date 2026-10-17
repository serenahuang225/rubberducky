"""Model readiness, reported separately from application health.

This module only inspects configuration. It must never import model libraries, download
weights or contact a provider, so health checks stay cheap and side-effect free.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.config import ProviderName, Settings

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
        if not settings.tutor_local_model_load_enabled:
            return ModelReadiness(
                provider=provider,
                state="disabled",
                ready=False,
                is_mock=False,
                label="Local Transformers model (disabled)",
                model_id=settings.tutor_local_model_id,
                model_revision=settings.tutor_local_model_revision,
                detail=(
                    "Local model loading is opt-in; set TUTOR_LOCAL_MODEL_LOAD_ENABLED=true. "
                    "Nothing is downloaded at startup."
                ),
            )
        return ModelReadiness(
            provider=provider,
            state="not_loaded",
            ready=False,
            is_mock=False,
            label="Local Transformers model (not loaded)",
            model_id=settings.tutor_local_model_id,
            model_revision=settings.tutor_local_model_revision,
            detail="The model loads lazily on first use, never at startup.",
        )
    label = "Claude" if provider == "claude" else "OpenAI-compatible endpoint"
    if not settings.external_integrations_enabled:
        return ModelReadiness(
            provider=provider,
            state="disabled",
            ready=False,
            is_mock=False,
            label=f"{label} (disabled)",
            model_id=None,
            model_revision=None,
            detail="Remote providers require EXTERNAL_INTEGRATIONS_ENABLED=true.",
        )
    return ModelReadiness(
        provider=provider,
        state="unverified",
        ready=False,
        is_mock=False,
        label=f"{label} (unverified)",
        model_id=None,
        model_revision=None,
        detail="The provider is not contacted at startup, so its readiness is unverified.",
    )
