"""Fictional Chalk, Droid, and Daytona walkthrough. No external service is contacted."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SettingsDep
from app.api.errors import ApiError, ErrorEnvelope
from app.config import Settings
from app.demos.integrations import FictionalIntegrationDemos, build_fictional_integration_demos

router = APIRouter(tags=["demo"])


def _demo_enabled(settings: SettingsDep) -> Settings:
    if not settings.demo_bootstrap_enabled:
        raise ApiError(403, "bootstrap_disabled", "Demo bootstrap is disabled on this server.")
    return settings


@router.get(
    "/demo/integrations",
    response_model=FictionalIntegrationDemos,
    responses={403: {"model": ErrorEnvelope}},
    summary="Fictional Chalk, Droid, and Daytona demos (no external calls)",
)
def integration_demos(
    _settings_ok: Annotated[Settings, Depends(_demo_enabled)],
) -> FictionalIntegrationDemos:
    return build_fictional_integration_demos()
