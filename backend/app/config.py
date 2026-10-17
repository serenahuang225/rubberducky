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
