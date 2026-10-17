"""Curated curriculum contracts. These are shared, not personal learner records."""

from typing import Literal, Self

from pydantic import model_validator

from app.schemas.common import ContractModel, EntityId, LongText, ShortText, UtcDatetime

ObjectiveKind = Literal["procedure", "explanation", "transfer"]
ProblemKind = Literal["practice", "transfer", "explanation"]


class Concept(ContractModel):
    schema_version: Literal["concept.v1"] = "concept.v1"
    id: EntityId
    name: ShortText
    description: LongText
    created_at: UtcDatetime


class PrerequisiteEdge(ContractModel):
    """``prerequisite_id`` must be learned before ``concept_id``."""

    schema_version: Literal["prerequisite-edge.v1"] = "prerequisite-edge.v1"
    id: EntityId
    prerequisite_id: EntityId
    concept_id: EntityId
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _not_self_loop(self) -> Self:
        if self.prerequisite_id == self.concept_id:
            raise ValueError("a concept cannot be its own prerequisite")
        return self


class LearningObjective(ContractModel):
    schema_version: Literal["learning-objective.v1"] = "learning-objective.v1"
    id: EntityId
    concept_id: EntityId
    kind: ObjectiveKind
    description: LongText
    created_at: UtcDatetime


class Problem(ContractModel):
    schema_version: Literal["problem.v1"] = "problem.v1"
    id: EntityId
    concept_id: EntityId
    objective_id: EntityId | None = None
    statement: ShortText
    kind: ProblemKind
    variant_of_problem_id: EntityId | None = None
    created_at: UtcDatetime
