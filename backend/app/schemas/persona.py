"""Persona-rule and accessibility contracts.

Durable appearance/personality choices follow a server-UTC cooldown. The comfort override and
accessibility preferences are separate, always editable, and never read or write the cooldown
timestamps.
"""

from typing import Literal, Self

from pydantic import ConfigDict, model_validator

from app.schemas.common import ContractModel, UtcDatetime
from app.schemas.learner import ComfortOverride, TutorConfiguration

PERSONA_CHANGE_COOLDOWN_SECONDS = 604800

# How the durable appearance/personality pair was affected by a request.
PersonaOutcome = Literal["initial_selection", "changed", "no_change"]
AnimationPreference = Literal["system", "full", "reduced", "off"]


class PersonaState(TutorConfiguration):
    """The stored configuration plus the server's view of the seven-day rule.

    ``next_change_available_at`` is the exact UTC instant a different appearance or personality
    is accepted (equality counts); it is ``None`` once the change is available. ``outcome`` is
    ``None`` when the state is only being read.
    """

    outcome: PersonaOutcome | None = None
    comfort_changed: bool = False
    server_now: UtcDatetime
    change_cooldown_seconds: int = PERSONA_CHANGE_COOLDOWN_SECONDS
    persona_locked: bool
    next_change_available_at: UtcDatetime | None = None


class ComfortOverrideRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["comfort-override-request.v1"] = "comfort-override-request.v1"
    comfort_override: ComfortOverride


class AccessibilityPreferences(ContractModel):
    """Effective accessibility choices. ``system`` animation follows the device setting."""

    schema_version: Literal["accessibility-preferences.v1"] = "accessibility-preferences.v1"
    animation: AnimationPreference = "system"
    sound_enabled: bool = True
    haptics_enabled: bool = True
    text_only: bool = False
    captions_enabled: bool = True
    updated_at: UtcDatetime | None = None


class AccessibilityPreferencesRequest(ContractModel):
    """Partial update: only the supplied fields change, and null is not a value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["accessibility-preferences-request.v1"] = (
        "accessibility-preferences-request.v1"
    )
    animation: AnimationPreference | None = None
    sound_enabled: bool | None = None
    haptics_enabled: bool | None = None
    text_only: bool | None = None
    captions_enabled: bool | None = None

    @model_validator(mode="after")
    def _no_explicit_null(self) -> Self:
        for name in self.model_fields_set - {"schema_version"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null; omit it to leave it unchanged")
        return self
