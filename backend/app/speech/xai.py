"""xAI speech-to-text and text-to-speech. No reasoning call lives here.

The tutor writes the words. ``synthesize`` is given that text and nothing else: no second
model, no rewrite instructions. The API key stays in the Authorization header.
"""

from typing import Protocol

import httpx

from app.config import Settings

XAI_ORIGIN = "https://api.x.ai"
_STT_PATH = "/v1/stt"
_TTS_PATH = "/v1/tts"


class SpeechError(Exception):
    """A learner-safe speech failure. The message never includes a response body or a key."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SpeechClient(Protocol):
    def transcribe(self, audio: bytes, content_type: str, filename: str) -> str: ...

    def synthesize(self, text: str) -> bytes: ...


def speech_enabled(settings: Settings) -> bool:
    """Both switches and a key. A key sitting in the environment does not turn speech on."""
    key = settings.xai_api_key
    return bool(
        settings.external_integrations_enabled
        and settings.xai_speech_enabled
        and key is not None
        and key.get_secret_value().strip()
    )


class XaiSpeechClient:
    """HTTP client for speech-to-text and text-to-speech. Built on first use, not at import."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        voice_id: str,
        language: str,
        http: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.voice_id = voice_id
        self.language = language
        self._auth = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(
            base_url=XAI_ORIGIN,
            follow_redirects=False,
            timeout=httpx.Timeout(30.0),
            headers=self._auth,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, *, http: httpx.Client | None = None
    ) -> "XaiSpeechClient":
        if not speech_enabled(settings) or settings.xai_api_key is None:
            raise SpeechError("Hold to talk is not configured.")
        return cls(
            api_key=settings.xai_api_key.get_secret_value(),
            model=settings.xai_stt_model,
            voice_id=settings.xai_tts_voice,
            language=settings.xai_tts_language,
            http=http,
        )

    def transcribe(self, audio: bytes, content_type: str, filename: str) -> str:
        # Option fields precede the file. Container formats are detected from the bytes.
        try:
            # Text fields come first. The file must be the last part.
            response = self._http.post(
                _STT_PATH,
                headers=self._auth,
                files=[
                    ("model", (None, self.model)),
                    ("language", (None, self.language)),
                    ("format", (None, "true")),
                    ("file", (filename, audio, content_type)),
                ],
            )
        except httpx.HTTPError as error:
            raise SpeechError("xAI could not transcribe that recording.") from error
        _raise_for_status(response, "transcribe")
        try:
            payload = response.json()
        except ValueError as error:
            raise SpeechError("xAI transcription was not usable.") from error
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise SpeechError("xAI transcription was not usable.")
        return text

    def synthesize(self, text: str) -> bytes:
        """Speak ``text`` as given. The body has no model and no instructions to change it."""
        try:
            response = self._http.post(
                _TTS_PATH,
                headers=self._auth,
                json={
                    "text": text,
                    "voice_id": self.voice_id,
                    "language": self.language,
                    "text_normalization": True,
                    "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000},
                },
            )
        except httpx.HTTPError as error:
            raise SpeechError("xAI could not speak the reply.") from error
        _raise_for_status(response, "speak")
        kind = response.headers.get("content-type", "")
        if kind.startswith("application/json") or not response.content:
            raise SpeechError("xAI did not return audio for the reply.")
        return response.content


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        raise SpeechError("xAI refused the speech key.")
    raise SpeechError(f"xAI could not {action} (HTTP {response.status_code}).")
