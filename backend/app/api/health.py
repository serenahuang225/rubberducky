from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel

from app import __version__
from app.api.explanations import router as explanations_router
from app.config import Settings
from app.inference.readiness import ModelReadiness, describe_model_readiness

router = APIRouter(tags=["health"])
# Already included by create_app. The explanations routes stay on this router so the learner
# path is reachable without editing the app factory, and they never contact Factory or Daytona.
router.include_router(explanations_router)


class AppHealth(BaseModel):
    schema_version: Literal["health.v1"] = "health.v1"
    status: Literal["ok"] = "ok"
    service: Literal["rubberducky-api"] = "rubberducky-api"
    version: str
    time_utc: AwareDatetime


def get_app_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not configured")
    return settings


@router.get("/health", response_model=AppHealth, summary="Application liveness")
def health() -> AppHealth:
    return AppHealth(version=__version__, time_utc=datetime.now(UTC))


@router.get(
    "/health/model",
    response_model=ModelReadiness,
    summary="Tutor model readiness (separate from application health)",
)
def model_health(settings: Annotated[Settings, Depends(get_app_settings)]) -> ModelReadiness:
    return describe_model_readiness(settings)
