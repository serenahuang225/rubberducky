"""Contracts for waiting: the learner's wait preference and the silence-safe wait state.

Waiting is the learner's space. Nothing here is an observation: elapsed time never becomes
correctness, latency, frustration or fatigue, and the tutor never speaks because a timer ran
out. The only thing time can do is make an optional hint available to ask for.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel, UtcDatetime

MIN_WAIT_SECONDS = 5
MAX_WAIT_SECONDS = 300
DEFAULT_WAIT_SECONDS = 45


class WaitPreferenceRequest(ContractModel):
    schema_version: Literal["wait-preference-request.v1"] = "wait-preference-request.v1"
    wait_seconds: Annotated[int, Field(ge=MIN_WAIT_SECONDS, le=MAX_WAIT_SECONDS)]


class WaitPreference(ContractModel):
    schema_version: Literal["wait-preference.v1"] = "wait-preference.v1"
    wait_seconds: int
    source: Literal["preference", "default"]
    default_seconds: int = DEFAULT_WAIT_SECONDS
    min_seconds: int = MIN_WAIT_SECONDS
    max_seconds: int = MAX_WAIT_SECONDS
    updated_at: UtcDatetime | None = None


class WaitState(ContractModel):
    """Where the learner's thinking time stands, computed from stored activity and the clock."""

    schema_version: Literal["wait-state.v1"] = "wait-state.v1"
    session_id: Annotated[str, Field(max_length=64)]
    now: UtcDatetime
    wait_seconds: int
    wait_source: Literal["preference", "default"]
    last_activity_at: UtcDatetime
    still_thinking_at: UtcDatetime | None = None
    still_thinking_count: int = 0
    # When an optional hint becomes available to ask for (not pushed to the learner).
    quiet_hint_at: UtcDatetime
    quiet_hint_available: bool
    next_hint_level: Annotated[int, Field(ge=1, le=4)]
    # The tutor never interrupts on a timer; silence is missing evidence, not a signal.
    proactive_prompt: Literal["none"] = "none"
    silence_interpretation: Literal["missing_evidence"] = "missing_evidence"
