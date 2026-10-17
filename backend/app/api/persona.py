"""Persona rule, comfort override and accessibility preferences (all own-learner routes).

Appearance/personality changes follow the server-UTC seven-day rule. Comfort and
accessibility edits are never locked and never touch the persona timestamps. All times come
from the server clock; nothing the client sends can move them.
"""

import math

from fastapi import APIRouter

from app.api.deps import ScopedRepo
from app.api.errors import ApiError, ErrorEnvelope
from app.clock import utc_now
from app.learner import persona as rules
from app.schemas.persona import (
    AccessibilityPreferences,
    AccessibilityPreferencesRequest,
    ComfortOverrideRequest,
    PersonaState,
)
from app.schemas.tutor import TutorConfigurationRequest

router = APIRouter(tags=["persona"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
}


def _not_selected() -> ApiError:
    return ApiError(404, "persona_not_selected", "Choose an appearance and personality first.")


@router.get(
    "/me/tutor-configuration",
    response_model=PersonaState,
    responses=_ERRORS,
    summary="Own persona with the server's seven-day lock state and next change time",
)
def get_tutor_configuration(repo: ScopedRepo) -> PersonaState:
    try:
        return rules.get_persona(repo, utc_now())
    except rules.PersonaNotSelectedError as error:
        raise _not_selected() from error


@router.put(
    "/me/tutor-configuration",
    response_model=PersonaState,
    responses=_ERRORS,
    summary="Choose or change the persona; a different pair waits 604800 seconds (server UTC)",
)
def put_tutor_configuration(body: TutorConfigurationRequest, repo: ScopedRepo) -> PersonaState:
    """First selection records server time. An identical pair is a no-op that never resets the
    wait. A different pair before eligibility is a 409 `persona_change_locked` that writes
    nothing (including a bundled comfort override)."""
    now = utc_now()
    try:
        result = rules.select_persona(repo, body, now)
    except rules.PersonaLockedError as error:
        repo.db.rollback()
        available = error.next_change_available_at
        raise ApiError(
            409,
            "persona_change_locked",
            "Appearance and personality can change again at "
            f"{available.isoformat().replace('+00:00', 'Z')}. "
            "Comfort and accessibility settings can still be changed now.",
            headers={"Retry-After": str(max(1, math.ceil((available - now).total_seconds())))},
        ) from error
    repo.db.commit()
    return result


@router.put(
    "/me/comfort-override",
    response_model=PersonaState,
    responses=_ERRORS,
    summary="Immediate neutral/supportive or reduced-sass delivery; never locked",
)
def put_comfort_override(body: ComfortOverrideRequest, repo: ScopedRepo) -> PersonaState:
    try:
        result = rules.set_comfort_override(repo, body.comfort_override, utc_now())
    except rules.PersonaNotSelectedError as error:
        raise ApiError(
            409, "persona_not_selected", "Choose an appearance and personality first."
        ) from error
    repo.db.commit()
    return result


@router.get(
    "/me/accessibility-preferences",
    response_model=AccessibilityPreferences,
    responses=_ERRORS,
    summary="Own motion, sound, haptics, text-only and caption preferences",
)
def get_accessibility_preferences(repo: ScopedRepo) -> AccessibilityPreferences:
    return rules.get_accessibility(repo)


@router.patch(
    "/me/accessibility-preferences",
    response_model=AccessibilityPreferences,
    responses=_ERRORS,
    summary="Update only the supplied accessibility preferences; never locked, never persona",
)
def patch_accessibility_preferences(
    body: AccessibilityPreferencesRequest, repo: ScopedRepo
) -> AccessibilityPreferences:
    result = rules.update_accessibility(repo, body, utc_now())
    repo.db.commit()
    return result
