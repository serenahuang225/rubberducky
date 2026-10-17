"""Durable persona rule: server-UTC seven-day wait, comfort override and accessibility edits.

Only an *effective* change of appearance or personality is limited. The first selection and an
identical re-selection never start or restart the wait, and the comfort override and
accessibility preferences are stored apart from the durable pair so they can always be edited.

The wait is measured as a fixed 604800 seconds between UTC instants taken from the server
clock, never calendar days in some local zone and never a client-supplied time.
"""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import PreferenceRow, TutorConfigurationRow
from app.db.repositories import ScopedRepository
from app.learner.memory import set_preference
from app.learner.pairing import new_id
from app.schemas import TutorConfiguration
from app.schemas.learner import ComfortOverride
from app.schemas.persona import (
    PERSONA_CHANGE_COOLDOWN_SECONDS,
    AccessibilityPreferences,
    AccessibilityPreferencesRequest,
    PersonaOutcome,
    PersonaState,
)
from app.schemas.tutor import TutorConfigurationRequest

PERSONA_CHANGE_COOLDOWN = timedelta(seconds=PERSONA_CHANGE_COOLDOWN_SECONDS)
ACCESSIBILITY_KEY_PREFIX = "a11y_"
_ACCESSIBILITY_FIELDS = (
    "animation",
    "sound_enabled",
    "haptics_enabled",
    "text_only",
    "captions_enabled",
)


class PersonaLockedError(Exception):
    """A different appearance or personality is not yet allowed."""

    def __init__(self, next_change_available_at: datetime) -> None:
        super().__init__("persona change locked")
        self.next_change_available_at = next_change_available_at


class PersonaNotSelectedError(LookupError):
    """No first-run appearance/personality choice exists yet."""


def next_change_available_at(last_changed_at: datetime) -> datetime:
    return last_changed_at + PERSONA_CHANGE_COOLDOWN


def _load(repo: ScopedRepository) -> TutorConfigurationRow | None:
    # populate_existing: a compare-and-swap race must be judged on committed data, not on a
    # row object cached earlier in this session.
    return repo.db.execute(
        select(TutorConfigurationRow)
        .where(TutorConfigurationRow.learner_id == repo.learner_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _state(
    row: TutorConfigurationRow,
    now: datetime,
    outcome: PersonaOutcome | None,
    comfort_changed: bool,
) -> PersonaState:
    available = next_change_available_at(row.last_changed_at)
    locked = now < available
    config = TutorConfiguration.model_validate(row)
    return PersonaState(
        **config.model_dump(),
        outcome=outcome,
        comfort_changed=comfort_changed,
        server_now=now,
        persona_locked=locked,
        next_change_available_at=available if locked else None,
    )


def get_persona(repo: ScopedRepository, now: datetime) -> PersonaState:
    row = _load(repo)
    if row is None:
        raise PersonaNotSelectedError
    return _state(row, now, None, False)


def _apply_comfort(
    row: TutorConfigurationRow, comfort: ComfortOverride | None, now: datetime
) -> bool:
    if comfort is None or comfort == row.comfort_override:
        return False
    row.comfort_override = comfort
    row.comfort_updated_at = now
    return True


def _claim_change(
    repo: ScopedRepository,
    row: TutorConfigurationRow,
    body: TutorConfigurationRequest,
    now: datetime,
) -> bool:
    """Compare-and-swap the durable pair; exactly one competing request can succeed.

    The statement re-checks eligibility and the timestamp it observed, so a concurrent winner
    that already restarted the wait makes this update match nothing.
    """
    result = repo.db.execute(
        update(TutorConfigurationRow)
        .where(
            TutorConfigurationRow.learner_id == repo.learner_id,
            TutorConfigurationRow.last_changed_at == row.last_changed_at,
            TutorConfigurationRow.last_changed_at <= now - PERSONA_CHANGE_COOLDOWN,
        )
        .values(
            appearance=body.appearance,
            personality=body.personality,
            provenance="submitted",
            last_changed_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[object], result).rowcount == 1


def select_persona(
    repo: ScopedRepository, body: TutorConfigurationRequest, now: datetime
) -> PersonaState:
    """First selection, effective change, or no-op, with optional immediate comfort override.

    A rejected change writes nothing, including a comfort override sent in the same request.
    """
    for _ in range(3):
        row = _load(repo)
        outcome: PersonaOutcome
        if row is None:
            config = TutorConfiguration(
                id=new_id(),
                learner_id=repo.learner_id,
                appearance=body.appearance,
                personality=body.personality,
                comfort_override=body.comfort_override or "none",
                provenance="submitted",
                chosen_at=now,
                last_changed_at=now,
                comfort_updated_at=now if body.comfort_override not in (None, "none") else None,
            )
            repo.db.add(TutorConfigurationRow(**config.model_dump()))
            try:
                repo.db.flush()
            except IntegrityError:
                # A competing first selection committed; judge this one as a later request.
                repo.db.rollback()
                continue
            fresh = _load(repo)
            assert fresh is not None  # noqa: S101 - just inserted
            return _state(fresh, now, "initial_selection", False)

        if (row.appearance, row.personality) == (body.appearance, body.personality):
            outcome = "no_change"
        else:
            available = next_change_available_at(row.last_changed_at)
            if now < available:
                raise PersonaLockedError(available)
            if not _claim_change(repo, row, body, now):
                continue
            outcome = "changed"
            row = _load(repo) or row
        comfort_changed = _apply_comfort(row, body.comfort_override, now)
        repo.db.flush()
        return _state(row, now, outcome, comfort_changed)
    raise RuntimeError("persona selection did not settle")


def set_comfort_override(
    repo: ScopedRepository, comfort: ComfortOverride, now: datetime
) -> PersonaState:
    """Immediate neutral/supportive or reduced-sass delivery; never reads the cooldown."""
    row = _load(repo)
    if row is None:
        raise PersonaNotSelectedError
    changed = _apply_comfort(row, comfort, now)
    repo.db.flush()
    return _state(row, now, "no_change", changed)


def get_accessibility(repo: ScopedRepository) -> AccessibilityPreferences:
    rows = repo.db.execute(
        select(PreferenceRow).where(
            PreferenceRow.learner_id == repo.learner_id,
            PreferenceRow.key.in_([ACCESSIBILITY_KEY_PREFIX + n for n in _ACCESSIBILITY_FIELDS]),
        )
    ).scalars()
    values: dict[str, object] = {}
    latest: datetime | None = None
    for row in rows:
        values[row.key.removeprefix(ACCESSIBILITY_KEY_PREFIX)] = row.value
        latest = row.updated_at if latest is None else max(latest, row.updated_at)
    return AccessibilityPreferences(**values, updated_at=latest)  # type: ignore[arg-type]


def update_accessibility(
    repo: ScopedRepository, body: AccessibilityPreferencesRequest, now: datetime
) -> AccessibilityPreferences:
    """Persist only the supplied fields as the learner's own preferences."""
    for name in _ACCESSIBILITY_FIELDS:
        value = getattr(body, name)
        if value is not None:
            set_preference(repo, ACCESSIBILITY_KEY_PREFIX + name, value, now)
    return get_accessibility(repo)
