"""Record → xAI transcript → the existing tutor turn → xAI speaks that utterance.

Drawing and memory stay on the tutor turn. Text-to-speech receives the committed
learner-facing utterance and no other field.
"""

import base64

from app.clock import utc_now
from app.config import Settings
from app.db.database import Database
from app.db.repositories import ScopedRepository
from app.inference.providers import ProviderUnavailableError
from app.learner.pairing import LearnerScope
from app.schemas.tutor import MAX_UTTERANCE_CHARS, MAX_WORK_CHARS, HandholdMode, WorkRequest
from app.schemas.voice import VoiceTurnResult
from app.speech.xai import SpeechClient, SpeechError
from app.tutor.cancellation import current_epoch
from app.tutor.coordinator import TurnCommandError, execute_turn

MAX_AUDIO_BYTES = 4_000_000
MAX_SPOKEN_AUDIO_BYTES = 4_000_000
_AUDIO_TYPES = {
    "audio/webm": "clip.webm",
    "audio/mp4": "clip.mp4",
    "audio/mpeg": "clip.mp3",
    "audio/mp3": "clip.mp3",
    "audio/wav": "clip.wav",
    "audio/x-wav": "clip.wav",
    "audio/ogg": "clip.ogg",
    "audio/flac": "clip.flac",
    "audio/aac": "clip.aac",
    "audio/m4a": "clip.m4a",
    "audio/x-m4a": "clip.m4a",
}


class VoiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def normalize_audio_type(content_type: str | None) -> str:
    raw = (content_type or "").split(";", 1)[0].strip().lower()
    if raw not in _AUDIO_TYPES:
        raise VoiceError(
            415,
            "unsupported_audio",
            "That recording format cannot be transcribed. Try again in the browser.",
        )
    return raw


def read_audio(payload: bytes, content_type: str | None) -> tuple[bytes, str, str]:
    kind = normalize_audio_type(content_type)
    if len(payload) > MAX_AUDIO_BYTES:
        raise VoiceError(
            413,
            "audio_too_large",
            "That recording is too long. Hold to talk for a shorter moment.",
        )
    if len(payload) < 32:
        raise VoiceError(
            422,
            "audio_empty",
            "No speech was in that recording. Hold to talk a little longer.",
        )
    return payload, kind, _AUDIO_TYPES[kind]


def run_voice_turn(
    database: Database,
    scope: LearnerScope,
    settings: Settings,
    speech: SpeechClient,
    *,
    session_id: str,
    audio: bytes,
    content_type: str,
    filename: str,
    expected_revision: int,
    observed_epoch: int,
    handhold: HandholdMode,
    speak: bool,
    idempotency_key: str,
) -> VoiceTurnResult:
    _reject_if_stale(database, scope, session_id, expected_revision, observed_epoch)
    try:
        heard = speech.transcribe(audio, content_type, filename)
    except SpeechError as error:
        raise VoiceError(502, "speech_unavailable", error.message) from error
    transcript = " ".join(heard.split())[:MAX_WORK_CHARS]
    if not transcript:
        raise VoiceError(422, "audio_empty", "No words were heard. Hold to talk a little longer.")
    try:
        turn = execute_turn(
            database,
            scope,
            settings,
            session_id,
            "work",
            WorkRequest(
                expected_revision=expected_revision,
                text=transcript,
                input_mode="typed",
                handhold=handhold,
            ),
            idempotency_key,
            utc_now(),
        )
    except TurnCommandError:
        raise
    except ProviderUnavailableError as error:
        raise VoiceError(503, "provider_unavailable", str(error)) from error
    spoken = (turn.utterance or "").strip()[:MAX_UTTERANCE_CHARS]
    if turn.status != "committed" or not spoken:
        return VoiceTurnResult(
            transcript=transcript,
            speech_note="The reply was not committed, so nothing was spoken.",
            turn=turn,
        )
    if not speak:
        return VoiceTurnResult(
            transcript=transcript,
            speech_note="The reply is on the board. Sound was off, so it was not spoken.",
            turn=turn,
        )
    try:
        audio_bytes = speech.synthesize(spoken)
    except SpeechError as error:
        return VoiceTurnResult(
            transcript=transcript,
            speech_note=f"The reply is on the board. {error.message}",
            turn=turn,
        )
    if not audio_bytes or len(audio_bytes) > MAX_SPOKEN_AUDIO_BYTES:
        return VoiceTurnResult(
            transcript=transcript,
            speech_note="The reply is on the board. The spoken audio was not usable.",
            turn=turn,
        )
    return VoiceTurnResult(
        transcript=transcript,
        spoken_text=spoken,
        audio_mime="audio/mpeg",
        audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
        turn=turn,
    )


def _reject_if_stale(
    database: Database,
    scope: LearnerScope,
    session_id: str,
    expected_revision: int,
    observed_epoch: int,
) -> None:
    db = database.new_session()
    try:
        repo = ScopedRepository(db, scope)
        session = repo.require_session(session_id)
        if session.status != "active":
            raise VoiceError(409, "session_not_active", "The session is not active.")
        epoch = current_epoch(repo, session_id)
        if expected_revision != session.revision or observed_epoch != epoch:
            raise VoiceError(
                409,
                "revision_conflict",
                "The board moved on, so that recording was not sent.",
            )
    finally:
        db.close()
