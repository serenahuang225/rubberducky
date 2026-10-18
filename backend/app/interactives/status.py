"""Truthful activation status for Factory generation and Daytona checks.

Status is derived from configuration alone: nothing here starts a subprocess, imports an SDK
or contacts a service. ``configured_unverified`` is the strongest state this build can report,
because no live Factory or Daytona call has been made.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.interactives.endpoints import validate_daytona_api_url
from app.schemas.interactives import IntegrationState


class IntegrationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Literal["factory_droid", "daytona"]
    state: IntegrationState
    label: str
    detail: str
    missing: tuple[str, ...] = ()
    verified_at: None = None


class InteractiveIntegrationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["interactive-integrations.v1"] = "interactive-integrations.v1"
    factory: IntegrationStatus
    daytona: IntegrationStatus
    # What a learner sees when either integration is not usable.
    generated_release_possible: bool


def _factory_status(settings: Settings) -> IntegrationStatus:
    if not (settings.external_integrations_enabled and settings.factory_interactives_enabled):
        return IntegrationStatus(
            name="factory_droid",
            state="disabled",
            label="Factory Droid explanation generation (disabled)",
            detail=(
                "Needs EXTERNAL_INTEGRATIONS_ENABLED=true and FACTORY_INTERACTIVES_ENABLED=true. "
                "Nothing is started or contacted."
            ),
        )
    executable = settings.factory_droid_executable
    missing = [
        name
        for name, present in (
            ("FACTORY_DROID_EXECUTABLE", bool(executable)),
            (
                "FACTORY_DROID_EXECUTABLE (file not found)",
                not executable or Path(executable).is_file(),
            ),
            ("FACTORY_MODEL", bool(settings.factory_model)),
        )
        if not present
    ]
    if missing:
        return IntegrationStatus(
            name="factory_droid",
            state="not_configured",
            label="Factory Droid explanation generation (not configured)",
            detail="Missing configuration: " + ", ".join(missing) + ".",
            missing=tuple(missing),
        )
    return IntegrationStatus(
        name="factory_droid",
        state="configured_unverified",
        label="Factory Droid explanation generation (configured, unverified)",
        detail=(
            "The installed Droid CLI has not been run, so authentication, model access and "
            "credits are unverified. A bounded request is sent to it only when a generation "
            "is explicitly started."
        ),
    )


def _daytona_status(settings: Settings) -> IntegrationStatus:
    if not (settings.external_integrations_enabled and settings.daytona_checks_enabled):
        return IntegrationStatus(
            name="daytona",
            state="disabled",
            label="Daytona trusted candidate checks (disabled)",
            detail=(
                "Needs EXTERNAL_INTEGRATIONS_ENABLED=true and DAYTONA_CHECKS_ENABLED=true. "
                "No sandbox is created."
            ),
        )
    missing: list[str] = []
    key = settings.daytona_api_key
    if key is None or not key.get_secret_value():
        missing.append("DAYTONA_API_KEY")
    try:
        validate_daytona_api_url(settings.daytona_api_url)
    except ValueError:
        missing.append("DAYTONA_API_URL (must be an https daytona.io host)")
    if missing:
        return IntegrationStatus(
            name="daytona",
            state="not_configured",
            label="Daytona trusted candidate checks (not configured)",
            detail="Missing configuration: " + ", ".join(missing) + ".",
            missing=tuple(missing),
        )
    return IntegrationStatus(
        name="daytona",
        state="configured_unverified",
        label="Daytona trusted candidate checks (configured, unverified)",
        detail=(
            "The account, sandbox allowance, network policy and pricing are unverified. A "
            "private ephemeral sandbox is created only when a candidate check is explicitly "
            "started, and it is deleted by its exact ID afterwards."
        ),
    )


def describe_interactive_integrations(settings: Settings) -> InteractiveIntegrationStatus:
    factory = _factory_status(settings)
    daytona = _daytona_status(settings)
    return InteractiveIntegrationStatus(
        factory=factory,
        daytona=daytona,
        generated_release_possible=(
            factory.state == "configured_unverified" and daytona.state == "configured_unverified"
        ),
    )
