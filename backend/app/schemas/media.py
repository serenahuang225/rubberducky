"""Contracts for optional media: capabilities, bounded events and their uncertain outcomes.

A media event is never evidence. Transcripts stay provisional until final, and even a final
one only offers text for the learner to confirm or edit before it travels the normal typed
work path. Recognition candidates are uncertain and editable. Weak contextual cues only ever
produce a neutral clarification prompt: no emotion, fatigue, disability or identity is
inferred, and no mastery estimate changes. Raw audio, video and images are validated for
size and discarded; nothing here stores or logs them.
"""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.multimodal import limits
from app.schemas.common import Confidence, ContractModel, EntityId, ShortText

MediaSource = Literal["device", "simulated"]
MediaKind = Literal["image_snapshot", "transcript", "weak_context"]
CameraOrientation = Literal["student_facing", "work_facing"]
MediaStatus = Literal[
    "provisional",
    "final_accepted",
    "duplicate_final",
    "ignored_late",
    "perception_unavailable",
    "candidates_uncertain",
    "clarification_prompt",
]
WeakSignal = Literal["silence", "voice_level", "expression_cue", "gaze_cue", "posture_cue"]
# Real recognition/transcription need provider credentials that this build does not ship.
CapabilityStatus = Literal["unavailable"]


class _Event(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["media-event-request.v1"] = "media-event-request.v1"
    event_id: EntityId
    # The session revision and cancellation epoch the client last saw; stale events are refused.
    expected_revision: Annotated[int, Field(ge=0)]
    observed_epoch: Annotated[int, Field(ge=0)]
    source: MediaSource


class ImageSnapshotEvent(_Event):
    """One explicit, foreground capture. Bytes are optional and never retained."""

    kind: Literal["image_snapshot"]
    orientation: CameraOrientation
    trigger: Literal["explicit_capture"]
    mime: Literal["image/jpeg", "image/png"]
    width: Annotated[int, Field(ge=1, le=16_384)]
    height: Annotated[int, Field(ge=1, le=16_384)]
    # Unknown (None) when the frame stayed in device memory and nothing was read or uploaded.
    byte_size: Annotated[int, Field(ge=1, le=50_000_000)] | None = None
    image_base64: Annotated[str, Field(max_length=1_500_000)] | None = None


class TranscriptEvent(_Event):
    kind: Literal["transcript"]
    utterance_id: EntityId
    sequence: Annotated[int, Field(ge=0, le=10_000)]
    phase: Literal["interim", "final"]
    text: Annotated[str, Field(min_length=1, max_length=limits.MAX_TRANSCRIPT_CHARS)]
    confidence: Confidence | None = None


class WeakContextEvent(_Event):
    kind: Literal["weak_context"]
    signal: WeakSignal


MediaEventRequest = Annotated[
    ImageSnapshotEvent | TranscriptEvent | WeakContextEvent, Field(discriminator="kind")
]


class RecognitionCandidate(ContractModel):
    text: Annotated[str, Field(min_length=1, max_length=120)]
    confidence: Confidence
    status: Literal["uncertain"] = "uncertain"
    editable: Literal[True] = True
    synthetic: bool = True
    source: Literal["fixture"] = "fixture"


class MediaEventResult(ContractModel):
    schema_version: Literal["media-event-result.v1"] = "media-event-result.v1"
    event_id: EntityId
    kind: MediaKind
    status: MediaStatus
    simulated: bool
    session_id: EntityId
    session_revision: Annotated[int, Field(ge=0)]
    cancellation_epoch: Annotated[int, Field(ge=0)]
    replayed: bool = False
    candidates: list[RecognitionCandidate] = Field(default_factory=list)
    requires_confirmation: bool = False
    message: Annotated[str, Field(max_length=300)]
    # Fixed by contract: a media event is never an observation, step or mastery update.
    assessment_effect: Literal["none"] = "none"
    evidence_recorded: Literal[False] = False
    raw_media_retained: Literal[False] = False


class CapabilityState(ContractModel):
    status: CapabilityStatus
    detail: ShortText


class SpeechInterruptionState(ContractModel):
    supported: bool
    acoustic_barge_in: Literal[False] = False
    detail: ShortText


class MediaLimits(ContractModel):
    max_image_bytes: int
    max_image_edge: int
    max_image_events_per_minute: int
    max_image_events_per_session: int
    max_events_per_minute: int
    max_events_per_session: int
    max_transcript_chars: int


class MediaDefaults(ContractModel):
    raw_media_stored: Literal[False] = False
    raw_media_logged: Literal[False] = False
    transcripts_retained: Literal[False] = False
    provider_transmission: Literal["none_configured"] = "none_configured"


class FixtureState(ContractModel):
    enabled: bool
    detail: ShortText


class MediaDisclosures(ContractModel):
    local: list[ShortText]
    transmitted: list[ShortText]


class MediaCapabilities(ContractModel):
    schema_version: Literal["media-capabilities.v1"] = "media-capabilities.v1"
    perception: CapabilityState
    transcription: CapabilityState
    speech_interruption: SpeechInterruptionState
    fixtures: FixtureState
    limits: MediaLimits
    defaults: MediaDefaults
    disclosures: MediaDisclosures
