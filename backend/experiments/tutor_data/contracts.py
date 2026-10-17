"""Records for shared tutoring examples. These are data contracts, not a language model."""

from typing import Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId

ExampleProvenance = Literal[
    "fictional_shared", "teacher_generated", "learner_recording", "public_dataset"
]
ReviewStatus = Literal["reviewed", "unreviewed"]


class SharedExample(ContractModel):
    """One reviewed or withheld tutoring prompt/completion pair.

    A row may not name a learner. Per-learner language-model fine-tuning is out of scope.
    """

    schema_version: Literal["shared-tutor-example.v1"] = "shared-tutor-example.v1"
    example_id: EntityId
    source: str = Field(min_length=1, max_length=200)
    terms: str = Field(min_length=1, max_length=300)
    license: str = Field(min_length=1, max_length=80)
    review_status: ReviewStatus
    reviewer: str | None = Field(default=None, max_length=80)
    scenario_family: EntityId
    problem_family: EntityId
    concept_family: EntityId
    prompt: str = Field(min_length=1, max_length=2000)
    completion: str = Field(min_length=1, max_length=2000)
    private: bool = False
    provenance: ExampleProvenance = "fictional_shared"
    learner_id: str | None = None
    declared_split: Literal["train", "held_out"] | None = None
    forbidden_disclosure: str | None = Field(default=None, max_length=200)
    license_access: str | None = Field(default=None, max_length=300)
    field_mapping: str | None = Field(default=None, max_length=300)
    template_id: str | None = Field(default=None, max_length=80)
    provider: str | None = Field(default=None, max_length=40)
    model_id: str | None = Field(default=None, max_length=120)
    model_version: str | None = Field(default=None, max_length=80)
    cost_usd: float | None = Field(default=None, ge=0)


def family_key(example: SharedExample) -> str:
    return f"{example.scenario_family}|{example.problem_family}|{example.concept_family}"
