"""Hold-to-talk. The xAI key never leaves this process.

The browser posts one recording. xAI transcribes it, the existing tutor turn reads that
text with the board and memory, and xAI speaks only the committed utterance.
"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile

from app.api.deps import ScopeDep, SettingsDep, get_database
from app.api.errors import ApiError, ErrorEnvelope
from app.api.sessions import SessionIdPath
from app.config import Settings
from app.db.database import Database
from app.inference.providers import ProviderUnavailableError
from app.schemas.tutor import HandholdMode
from app.schemas.voice import VoiceTurnResult
from app.speech.service import MAX_AUDIO_BYTES, VoiceError, read_audio, run_voice_turn
from app.speech.xai import SpeechClient, SpeechError, XaiSpeechClient, speech_enabled
from app.tutor.coordinator import TurnCommandError

router = APIRouter(tags=["voice"])

DatabaseDep = Annotated[Database, Depends(get_database)]
IdempotencyKeyHeader = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    415: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    502: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}
def resolve_speech_client(request: Request, settings: Settings) -> SpeechClient:
    if not speech_enabled(settings):
        raise VoiceError(
            503,
            "speech_unavailable",
            "Hold to talk is off. Set XAI_SPEECH_ENABLED and EXTERNAL_INTEGRATIONS_ENABLED, "
            "and keep the xAI key on the server.",
        )
    override = getattr(request.app.state, "speech_client", None)
    if override is not None:
        return cast(SpeechClient, override)
    cached = getattr(request.app.state, "xai_speech_client", None)
    if isinstance(cached, XaiSpeechClient):
        return cached
    try:
        client = XaiSpeechClient.from_settings(settings)
    except SpeechError as error:
        raise VoiceError(503, "speech_unavailable", error.message) from error
    request.app.state.xai_speech_client = client
    return client


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _handhold(value: str) -> HandholdMode:
    if value == "guided":
        return "guided"
    if value == "hands_off":
        return "hands_off"
    if value == "balanced":
        return "balanced"
    raise ApiError(422, "invalid_handhold", "Handhold must be guided, balanced, or hands off.")


@router.post(
    "/sessions/{session_id}/voice/turn",
    response_model=VoiceTurnResult,
    responses=_ERRORS,
    summary="Hold-to-talk: transcribe, ask the tutor, then speak only that reply",
)
def post_voice_turn(
    request: Request,
    session_id: SessionIdPath,
    idempotency_key: IdempotencyKeyHeader,
    scope: ScopeDep,
    database: DatabaseDep,
    settings: SettingsDep,
    audio: Annotated[UploadFile, File()],
    expected_revision: Annotated[int, Form(ge=0)],
    observed_epoch: Annotated[int, Form(ge=0)],
    handhold: Annotated[str, Form()] = "balanced",
    speak: Annotated[str, Form()] = "true",
) -> VoiceTurnResult:
    mode = _handhold(handhold)
    try:
        speech = resolve_speech_client(request, settings)
        payload = audio.file.read(MAX_AUDIO_BYTES + 1)
        data, content_type, filename = read_audio(payload, audio.content_type)
        return run_voice_turn(
            database,
            scope,
            settings,
            speech,
            session_id=session_id,
            audio=data,
            content_type=content_type,
            filename=filename,
            expected_revision=expected_revision,
            observed_epoch=observed_epoch,
            handhold=mode,
            speak=_flag(speak),
            idempotency_key=idempotency_key,
        )
    except VoiceError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except TurnCommandError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    except ProviderUnavailableError as error:
        raise ApiError(503, "provider_unavailable", str(error)) from error
