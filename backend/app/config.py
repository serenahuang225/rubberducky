"""Typed runtime configuration.

Settings come from process environment variables only. The repository-root ``.env`` is
user-owned and is never read; an explicit file can be opted into with ``TUTOR_ENV_FILE``.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["mock", "transformers", "endpoint", "claude"]

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
