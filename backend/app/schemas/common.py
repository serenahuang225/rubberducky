"""Shared contract primitives: versions, IDs, UTC timestamps, provenance and confidence.

Pydantic models here are data contracts, not statistical models. Every record carries an
explicit ``schema_version`` literal so an unsupported version is rejected rather than coerced.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Naive datetimes (and ISO strings without an offset) are rejected; aware values are
# normalized to UTC so storage and comparison never depend on the client's time zone.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]

EntityId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]

# A probability-like confidence. NaN/inf and values outside [0, 1] are rejected.
Confidence = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=500)]
SourceIds = Annotated[list[EntityId], Field(max_length=20)]

# "fictional_seed": reproducible demo history written by the seed command.
# "submitted": an event that actually happened through the running application.
Provenance = Literal["fictional_seed", "submitted"]
PROVENANCE_VALUES: tuple[Provenance, ...] = ("fictional_seed", "submitted")

EvidenceKind = Literal["self_report", "observed_work", "inference", "verified_assessment"]
EVIDENCE_KIND_VALUES: tuple[EvidenceKind, ...] = (
    "self_report",
    "observed_work",
    "inference",
    "verified_assessment",
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)
