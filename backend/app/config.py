"""Typed runtime configuration.

Settings come from process environment variables only. The repository-root ``.env`` is
user-owned and is never read; an explicit file can be opted into with ``TUTOR_ENV_FILE``.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["mock", "transformers", "endpoint", "claude"]

LocalDevice = Literal["cpu", "mps", "cuda"]
LocalDtype = Literal["float32", "bfloat16", "float16"]

DEFAULT_LOCAL_MODEL_ID = "HuggingFaceTB/SmolLM2-135M-Instruct"
DEFAULT_LOCAL_MODEL_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
DEFAULT_CORS_ORIGINS = "http://127.0.0.1:3101,http://localhost:3101"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    tutor_provider: ProviderName = "mock"
    external_integrations_enabled: bool = False
    database_url: str = Field(default="sqlite:///./data/tutor.db", min_length=1)
    tutor_cors_origins: str = DEFAULT_CORS_ORIGINS
    tutor_local_model_id: str = Field(default=DEFAULT_LOCAL_MODEL_ID, min_length=1)
    tutor_local_model_revision: str = Field(default=DEFAULT_LOCAL_MODEL_REVISION, min_length=1)
    tutor_local_model_load_enabled: bool = False
    tutor_local_device: LocalDevice = "cpu"
    tutor_local_dtype: LocalDtype = "float32"
    # Loading from the local Hugging Face cache only; fetching weights needs this explicit opt-in.
    tutor_local_allow_download: bool = False
    tutor_local_context_window_tokens: int = Field(default=8_192, ge=256, le=131_072)
    tutor_local_max_new_tokens: int = Field(default=512, ge=1, le=4_096)
    # Requests allowed to wait behind the one running generation; more are refused, not queued.
    tutor_local_max_queue: int = Field(default=2, ge=0, le=16)
    tutor_local_timeout_seconds: float = Field(default=120.0, gt=0, le=1_800)
    # Remote providers (Claude, OpenAI-compatible endpoint). Keys stay server-side.
    tutor_remote_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    tutor_remote_max_attempts: int = Field(default=3, ge=1, le=5)
    tutor_remote_backoff_seconds: float = Field(default=0.5, ge=0, le=30)
    tutor_remote_max_output_tokens: int = Field(default=512, ge=1, le=4_096)
    tutor_remote_max_request_chars: int = Field(default=32_000, ge=64, le=800_000)
    tutor_endpoint_base_url: str | None = None
    tutor_endpoint_model: str | None = None
    tutor_endpoint_api_key: SecretStr | None = None
    tutor_endpoint_streaming: bool = True
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None
    # Runtime explanation generation through the installed Factory Droid CLI (droid-sdk).
    # Needs external_integrations_enabled, this flag and an explicit executable path; the
    # presence of a key in the environment never activates it.
    factory_interactives_enabled: bool = False
    factory_droid_executable: str | None = None
    factory_model: str | None = None
    factory_reasoning_effort: Literal["off", "low", "medium"] = "low"
    factory_api_key: SecretStr | None = None
    factory_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    factory_max_prompt_chars: int = Field(default=4_000, ge=200, le=16_000)
    factory_max_output_chars: int = Field(default=6_000, ge=200, le=32_000)
    # Credits reported by the Droid CLI. Not a spending cap: a run is interrupted once a
    # reported total passes this, and a result without reported credits is refused.
    factory_max_credits: float = Field(default=5.0, ge=0, le=1_000)
    # Trusted candidate checks in a private ephemeral Daytona sandbox.
    daytona_checks_enabled: bool = False
    daytona_api_key: SecretStr | None = None
    daytona_api_url: str = "https://app.daytona.io/api"
    daytona_target: str = Field(default="us", min_length=1, max_length=32)
    daytona_create_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    daytona_exec_timeout_seconds: int = Field(default=30, ge=1, le=120)
    daytona_cleanup_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    # Deterministic, explicitly "simulated" media events (fake transcripts, synthetic uncertain
    # recognition) for tests and demos. They never stand in for real recognition.
    tutor_media_fixtures_enabled: bool = True
    # Lets a device create a new, empty fictional demo learner. Never exposes existing history.
    demo_bootstrap_enabled: bool = True
    pairing_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(o.strip() for o in self.tutor_cors_origins.split(",") if o.strip())


def load_settings() -> Settings:
    env_file = os.environ.get("TUTOR_ENV_FILE")
    if env_file:
        return Settings(_env_file=Path(env_file))
    return Settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
