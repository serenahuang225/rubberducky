"""Accept, bound and classify one media event; never keep raw media or assess anything.

Order of checks: learner/session scope (404), idempotent replay, stale revision/epoch (409),
source honesty (409), size and rate bounds (413/429), then the deterministic outcome. A
rejected event leaves no row. Accepted events store metadata only, so a late event after an
interruption or a changed revision can add no speech, drawing, evidence or memory: this
module has no write path to any of them.
"""

import base64
import binascii
import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db.models import MediaEventRow
from app.db.repositories import ScopedRepository
from app.multimodal import limits
from app.schemas.media import (
    CapabilityState,
    FixtureState,
    ImageSnapshotEvent,
    MediaCapabilities,
    MediaDefaults,
    MediaDisclosures,
    MediaEventRequest,
    MediaEventResult,
    MediaLimits,
    RecognitionCandidate,
    SpeechInterruptionState,
    TranscriptEvent,
    WeakContextEvent,
)
from app.tutor.cancellation import current_epoch


class MediaEventError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# A fixed, clearly synthetic reading of an ambiguous handwritten step. Never real recognition.
_FIXTURE_CANDIDATES = (
    ("2x + 6 = 14", 0.41),
    ("2x + 3 = 14", 0.33),
)
CLARIFICATION = (
    "I can't tell anything about you from that, so I won't guess. "
    "If you would like to tell me how things are going, you can say or type it."
)


def _transmitted(settings: Settings) -> list[str]:
    if settings.tutor_provider == "claude" and settings.external_integrations_enabled:
        return [
            "A question you type, upload, or screenshot at the start is sent to Anthropic "
            "so Claude can read it and write the note you see. The picture is not saved.",
            "Voice and camera from the media panel are still not sent.",
        ]
    return [
        "No provider is configured, so no audio, image or transcript is sent anywhere.",
        "If a provider is added later, what is sent will be listed here first.",
    ]


def capabilities(settings: Settings) -> MediaCapabilities:
    fixtures = settings.tutor_media_fixtures_enabled
    return MediaCapabilities(
        perception=CapabilityState(
            status="unavailable",
            detail="Image understanding is not configured; photos are never read or described.",
        ),
        transcription=CapabilityState(
            status="unavailable",
            detail="Speech recognition is not configured; nothing you say is transcribed.",
        ),
        speech_interruption=SpeechInterruptionState(
            supported=True,
            detail=(
                "Stop speaking and a deterministic barge-in event stop the tutor's voice; "
                "interruption by detecting your voice is not available."
            ),
        ),
        fixtures=FixtureState(
            enabled=fixtures,
            detail=(
                "Simulated media events are enabled for testing; they are labeled simulated."
                if fixtures
                else "Simulated media events are turned off."
            ),
        ),
        limits=MediaLimits(
            max_image_bytes=limits.MAX_IMAGE_BYTES,
            max_image_edge=limits.MAX_IMAGE_EDGE,
            max_image_events_per_minute=limits.MAX_IMAGE_EVENTS_PER_MINUTE,
            max_image_events_per_session=limits.MAX_IMAGE_EVENTS_PER_SESSION,
            max_events_per_minute=limits.MAX_EVENTS_PER_MINUTE,
            max_events_per_session=limits.MAX_EVENTS_PER_SESSION,
            max_transcript_chars=limits.MAX_TRANSCRIPT_CHARS,
        ),
        defaults=MediaDefaults(),
        disclosures=MediaDisclosures(
            local=[
                "The microphone and camera stay off until you turn them on, and stop when you "
                "leave this screen or the app.",
                "Nothing is recorded: audio, video and photos are not saved or logged.",
                "Text you confirm as a step is stored like any typed step; you can delete it.",
            ],
            transmitted=_transmitted(settings),
        ),
    )


def _request_hash(body: MediaEventRequest) -> str:
    payload = body.model_dump(mode="json", exclude={"image_base64"})
    if isinstance(body, ImageSnapshotEvent):
        payload["has_inline_bytes"] = body.image_base64 is not None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _inline_size(encoded: str) -> int:
    try:
        return len(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError):
        raise MediaEventError(422, "invalid_media", "The image data is not valid base64.") from None


def _count(
    repo: ScopedRepository,
    session_id: str,
    *,
    kind: str | None = None,
    since: datetime | None = None,
) -> int:
    query = (
        select(func.count())
        .select_from(MediaEventRow)
        .where(MediaEventRow.learner_id == repo.learner_id, MediaEventRow.session_id == session_id)
    )
    if kind is not None:
        query = query.where(MediaEventRow.kind == kind)
    if since is not None:
        query = query.where(MediaEventRow.created_at >= since)
    return int(repo.db.execute(query).scalar_one())


def _check_bounds(
    repo: ScopedRepository, session_id: str, body: MediaEventRequest, now: datetime
) -> None:
    window = now - timedelta(seconds=limits.RATE_WINDOW_SECONDS)
    if isinstance(body, ImageSnapshotEvent):
        size = body.byte_size or 0
        if body.image_base64 is not None:
            size = max(size, _inline_size(body.image_base64))
        if size > limits.MAX_IMAGE_BYTES or max(body.width, body.height) > limits.MAX_IMAGE_EDGE:
            raise MediaEventError(
                413,
                "media_too_large",
                f"A photo may be at most {limits.MAX_IMAGE_BYTES // 1024} KiB and "
                f"{limits.MAX_IMAGE_EDGE} px on a side.",
            )
        if _count(repo, session_id, kind="image_snapshot") >= limits.MAX_IMAGE_EVENTS_PER_SESSION:
            raise MediaEventError(
                429, "media_session_limit", "This session has reached its photo limit."
            )
        if (
            _count(repo, session_id, kind="image_snapshot", since=window)
            >= limits.MAX_IMAGE_EVENTS_PER_MINUTE
        ):
            raise MediaEventError(
                429, "media_rate_limited", "Photos are limited per minute; wait a moment."
            )
    if _count(repo, session_id) >= limits.MAX_EVENTS_PER_SESSION:
        raise MediaEventError(
            429, "media_session_limit", "This session has reached its media event limit."
        )
    if _count(repo, session_id, since=window) >= limits.MAX_EVENTS_PER_MINUTE:
        raise MediaEventError(
            429, "media_rate_limited", "Media events are limited per minute; wait a moment."
        )


def _check_source(settings: Settings, body: MediaEventRequest) -> None:
    if body.source == "simulated" and not settings.tutor_media_fixtures_enabled:
        raise MediaEventError(
            409, "fixtures_disabled", "Simulated media events are turned off on this server."
        )
    if isinstance(body, TranscriptEvent) and body.source == "device":
        raise MediaEventError(
            409,
            "transcription_unavailable",
            "Speech recognition is not configured, so no live transcript can be accepted.",
        )


def _unseen_latest_interim(repo: ScopedRepository, session_id: str, utterance_id: str) -> int:
    latest = repo.db.execute(
        select(func.max(MediaEventRow.sequence)).where(
            MediaEventRow.learner_id == repo.learner_id,
            MediaEventRow.session_id == session_id,
            MediaEventRow.utterance_id == utterance_id,
            MediaEventRow.status.in_(("provisional", "final_accepted")),
        )
    ).scalar_one_or_none()
    return -1 if latest is None else int(latest)


def _final_accepted(repo: ScopedRepository, session_id: str, utterance_id: str) -> bool:
    return (
        repo.db.execute(
            select(MediaEventRow.event_id).where(
                MediaEventRow.learner_id == repo.learner_id,
                MediaEventRow.session_id == session_id,
                MediaEventRow.final_key == utterance_id,
            )
        ).first()
        is not None
    )


def _classify(
    repo: ScopedRepository, session_id: str, body: MediaEventRequest
) -> tuple[str, str, list[RecognitionCandidate], bool, str | None]:
    """Returns (status, message, candidates, requires_confirmation, final_key)."""
    if isinstance(body, WeakContextEvent):
        return "clarification_prompt", CLARIFICATION, [], False, None
    if isinstance(body, ImageSnapshotEvent):
        if body.source == "device":
            return (
                "perception_unavailable",
                "Image understanding is not configured, so the photo was not read. "
                "Type your step instead.",
                [],
                False,
                None,
            )
        candidates = [
            RecognitionCandidate(text=text, confidence=confidence)
            for text, confidence in _FIXTURE_CANDIDATES
        ]
        return (
            "candidates_uncertain",
            "Synthetic test readings, not real recognition. Check or edit one before using it.",
            candidates,
            True,
            None,
        )
    late = _final_accepted(repo, session_id, body.utterance_id)
    if body.phase == "interim":
        if late or body.sequence <= _unseen_latest_interim(repo, session_id, body.utterance_id):
            return "ignored_late", "That update arrived late and was ignored.", [], False, None
        return "provisional", "Provisional text: not yet final and not checked.", [], False, None
    if late:
        return "duplicate_final", "That utterance was already finalized.", [], False, None
    return (
        "final_accepted",
        "Final text is ready to confirm or edit. It is not checked until you submit it as a step.",
        [],
        True,
        body.utterance_id,
    )


def handle_media_event(
    repo: ScopedRepository,
    settings: Settings,
    session_id: str,
    body: MediaEventRequest,
    now: datetime,
) -> MediaEventResult:
    session = repo.require_session(session_id)
    if session.status != "active":
        raise MediaEventError(409, "session_not_active", "The session is not active.")
    request_hash = _request_hash(body)
    existing = repo.db.execute(
        select(MediaEventRow).where(
            MediaEventRow.learner_id == repo.learner_id, MediaEventRow.event_id == body.event_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash or existing.session_id != session_id:
            raise MediaEventError(
                409, "idempotency_conflict", "That event id was already used for different content."
            )
        stored = MediaEventResult.model_validate(existing.result)
        return stored.model_copy(update={"replayed": True})
    epoch = current_epoch(repo, session_id)
    if body.expected_revision != session.revision:
        raise MediaEventError(
            409, "stale_revision", "The session moved on; this media event is out of date."
        )
    if body.observed_epoch != epoch:
        raise MediaEventError(
            409,
            "stale_epoch",
            "The reply was stopped or replaced; this media event is out of date.",
        )
    _check_source(settings, body)
    _check_bounds(repo, session_id, body, now)
    status, message, candidates, confirm, final_key = _classify(repo, session_id, body)
    result = MediaEventResult(
        event_id=body.event_id,
        kind=body.kind,
        status=status,  # type: ignore[arg-type]
        simulated=body.source == "simulated",
        session_id=session_id,
        session_revision=session.revision,
        cancellation_epoch=epoch,
        candidates=candidates,
        requires_confirmation=confirm,
        message=message,
    )
    row = MediaEventRow(
        learner_id=repo.learner_id,
        event_id=body.event_id,
        session_id=session_id,
        kind=body.kind,
        source=body.source,
        status=status,
        utterance_id=body.utterance_id if isinstance(body, TranscriptEvent) else None,
        sequence=body.sequence if isinstance(body, TranscriptEvent) else None,
        final_key=final_key,
        base_revision=session.revision,
        base_epoch=epoch,
        byte_size=body.byte_size if isinstance(body, ImageSnapshotEvent) else None,
        request_hash=request_hash,
        result=result.model_dump(mode="json"),
        created_at=now,
    )
    try:
        with repo.db.begin_nested():
            repo.db.add(row)
            repo.db.flush()
    except IntegrityError:
        # A concurrent final for the same utterance won the unique key: this one is a duplicate.
        row.final_key = None
        row.status = "duplicate_final"
        result = result.model_copy(
            update={
                "status": "duplicate_final",
                "requires_confirmation": False,
                "message": "That utterance was already finalized.",
            }
        )
        row.result = result.model_dump(mode="json")
        repo.db.add(row)
        repo.db.flush()
    return result
