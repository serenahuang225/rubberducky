"""Hold-to-talk uses xAI only to hear and to speak. The tutor writes the reply.

Outbound sockets stay closed. A fake speech client records the exact text it was asked
to speak, and the HTTP client test checks that text-to-speech is not a chat completion.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.config import Settings
from app.db.database import Database
from app.db.models import TutorTurnRow
from app.main import create_app
from app.speech.xai import SpeechError, XaiSpeechClient
from tests.conftest import bootstrap

CANARY = "xai-test-SECRET-0123456789"
CLIP = b"\x1a\x45\xdf\xa3" + b"spoken-bytes" * 8


class FakeSpeech:
    def __init__(self, transcript: str = "why do we subtract 3") -> None:
        self.transcript = transcript
        self.spoken: list[str] = []
        self.calls: list[str] = []
        self.fail_tts = False
        self.fail_stt = False

    def transcribe(self, audio: bytes, content_type: str, filename: str) -> str:
        assert audio and content_type and filename
        self.calls.append("transcribe")
        if self.fail_stt:
            raise SpeechError("xAI could not transcribe that recording.")
        return self.transcript

    def synthesize(self, text: str) -> bytes:
        self.calls.append("synthesize")
        self.spoken.append(text)
        if self.fail_tts:
            raise SpeechError("xAI could not speak (HTTP 503).")
        return b"ID3-spoken-reply"


def _enabled(url: str) -> Settings:
    return Settings(
        database_url=url,
        external_integrations_enabled=True,
        xai_speech_enabled=True,
        xai_api_key=SecretStr(CANARY),
    )


def _open(settings: Settings, speech: FakeSpeech | None = None) -> TestClient:
    app = create_app(settings)
    if speech is not None:
        app.state.speech_client = speech
    return TestClient(app)


def _checked_in(client: TestClient, headers: dict[str, str]) -> tuple[str, int]:
    created = client.post("/sessions", json={"goal": "practice"}, headers=headers)
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    checked = client.post(
        f"/sessions/{session_id}/check-in",
        json={"expected_revision": 0},
        headers={**headers, "Idempotency-Key": "checkin-voice-01"},
    )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["status"] == "committed"
    return session_id, body["session_revision"]


def _post(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    revision: int,
    *,
    key: str = "voice-turn-01",
    speak: str = "true",
    epoch: str = "0",
    audio: bytes = CLIP,
    content_type: str = "audio/webm",
) -> httpx.Response:
    return client.post(
        f"/sessions/{session_id}/voice/turn",
        headers={**headers, "Idempotency-Key": key},
        data={
            "expected_revision": str(revision),
            "observed_epoch": epoch,
            "handhold": "balanced",
            "speak": speak,
        },
        files={"audio": ("clip.webm", audio, content_type)},
    )


def test_hold_to_talk_is_off_until_explicitly_enabled(seeded_db_url: str) -> None:
    with _open(Settings(database_url=seeded_db_url)) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(client, headers, session_id, revision)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "speech_unavailable"
    assert CANARY not in response.text


def test_xai_speaks_only_the_tutor_utterance(seeded_db_url: str, database: Database) -> None:
    speech = FakeSpeech()
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(client, headers, session_id, revision)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "why do we subtract 3"
    assert body["turn"]["status"] == "committed"
    utterance = body["turn"]["utterance"]
    assert utterance
    assert body["spoken_text"] == utterance
    assert speech.spoken == [utterance]
    assert speech.calls == ["transcribe", "synthesize"]
    assert "why do we subtract 3" not in speech.spoken
    assert body["audio_mime"] == "audio/mpeg"
    assert body["audio_base64"]
    assert CANARY not in response.text
    assert isinstance(body["turn"]["drawings"], list)
    assert body["spoken_text"] != body["turn"].get("decision_justification")
    with database.transaction() as db:
        turns = db.execute(
            select(func.count())
            .select_from(TutorTurnRow)
            .where(TutorTurnRow.session_id == session_id)
        ).scalar_one()
    assert turns >= 1


def test_a_failed_transcription_does_not_ask_the_tutor(
    seeded_db_url: str, database: Database
) -> None:
    speech = FakeSpeech()
    speech.fail_stt = True
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        before = _turn_count(database, session_id)
        response = _post(client, headers, session_id, revision, key="voice-turn-stt")
    assert response.status_code == 502
    assert speech.spoken == []
    assert _turn_count(database, session_id) == before


def test_silence_is_not_sent_to_the_tutor(seeded_db_url: str) -> None:
    speech = FakeSpeech(transcript="   ")
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(client, headers, session_id, revision, key="voice-turn-quiet")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "audio_empty"
    assert speech.calls == ["transcribe"]


def test_speech_failure_keeps_the_committed_reply(seeded_db_url: str) -> None:
    speech = FakeSpeech()
    speech.fail_tts = True
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(client, headers, session_id, revision, key="voice-turn-tts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["turn"]["status"] == "committed"
    assert body["spoken_text"] is None
    assert body["audio_base64"] is None
    assert "board" in body["speech_note"]
    assert CANARY not in response.text


def test_sound_off_skips_speech(seeded_db_url: str) -> None:
    speech = FakeSpeech()
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(
            client, headers, session_id, revision, key="voice-turn-mute", speak="false"
        )
    assert response.status_code == 200, response.text
    assert response.json()["turn"]["status"] == "committed"
    assert speech.calls == ["transcribe"]


def test_a_stale_recording_is_not_transcribed(seeded_db_url: str) -> None:
    speech = FakeSpeech()
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(client, headers, session_id, revision + 5, key="voice-turn-stale")
    assert response.status_code == 409
    assert speech.calls == []


def test_oversized_audio_is_refused(seeded_db_url: str) -> None:
    speech = FakeSpeech()
    with _open(_enabled(seeded_db_url), speech) as client:
        _, headers = bootstrap(client)
        session_id, revision = _checked_in(client, headers)
        response = _post(
            client,
            headers,
            session_id,
            revision,
            key="voice-turn-big",
            audio=b"x" * (4_000_001),
        )
    assert response.status_code == 413
    assert speech.calls == []


def _turn_count(database: Database, session_id: str) -> int:
    with database.transaction() as db:
        return int(
            db.execute(
                select(func.count())
                .select_from(TutorTurnRow)
                .where(TutorTurnRow.session_id == session_id)
            ).scalar_one()
        )


def test_text_to_speech_posts_the_utterance_and_not_a_chat(
    no_network: list[tuple[str, object]],
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/stt":
            body = request.content
            assert body.find(b'name="model"') < body.find(b'name="file"')
            return httpx.Response(200, json={"text": "subtract three", "duration": 1.0})
        if request.url.path == "/v1/tts":
            payload = json.loads(request.content)
            assert payload["text"] == "Try the other side."
            assert "model" not in payload
            assert "messages" not in payload
            assert request.headers["authorization"] == f"Bearer {CANARY}"
            return httpx.Response(200, content=b"ID3ok", headers={"content-type": "audio/mpeg"})
        return httpx.Response(404, json={"error": CANARY})

    client = XaiSpeechClient(
        api_key=CANARY,
        model="grok-voice-transcribe-2.0",
        voice_id="luna",
        language="en",
        http=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.x.ai"),
    )
    assert client.transcribe(CLIP, "audio/webm", "clip.webm") == "subtract three"
    assert client.synthesize("Try the other side.") == b"ID3ok"
    assert [request.url.path for request in seen] == ["/v1/stt", "/v1/tts"]
    assert no_network == []


def test_speech_errors_do_not_echo_the_provider_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad {CANARY}")

    client = XaiSpeechClient(
        api_key=CANARY,
        model="grok-voice-transcribe-2.0",
        voice_id="luna",
        language="en",
        http=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.x.ai"),
    )
    with pytest.raises(SpeechError) as caught:
        client.transcribe(CLIP, "audio/webm", "clip.webm")
    assert CANARY not in caught.value.message
    assert "401" not in caught.value.message or "refused" in caught.value.message
