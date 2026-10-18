"""Hold-to-talk result: the tutor turn, plus audio of that turn's utterance only."""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel
from app.schemas.tutor import TutorTurnResult


class VoiceTurnResult(ContractModel):
    schema_version: Literal["voice-turn.v1"] = "voice-turn.v1"
    transcript: Annotated[str, Field(min_length=1, max_length=500)]
    # The exact tutor utterance sent to text-to-speech. Null when nothing was spoken.
    spoken_text: Annotated[str, Field(max_length=1_200)] | None = None
    audio_mime: Literal["audio/mpeg"] | None = None
    audio_base64: str | None = None
    speech_note: Annotated[str, Field(max_length=300)] | None = None
    turn: TutorTurnResult
