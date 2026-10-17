"""Explanation-rubric hooks kept separate from mathematical verification.

A rubric judgment is a pedagogical inference (``evidence_kind='inference'``) with bounded
confidence. It never changes a ``VerificationResult`` and is never executed: explanation text is
only compared against fixed phrases. The deterministic keyword judge is a transparent baseline;
a provider judge can implement the same protocol, and ``validate_judgment`` rejects proposals
that refer to unknown criteria or claim more certainty than the rubric allows.
"""

from typing import Annotated, Literal, Protocol

from pydantic import Field

from app.schemas.common import Confidence, ContractModel, EntityId, LongText, ShortText

CriterionStatus = Literal["met", "not_met", "unknown"]
JudgeKind = Literal["deterministic_keyword", "provider"]
MAX_EXPLANATION_CHARS = 500


class RubricCriterion(ContractModel):
    id: EntityId
    description: ShortText
    cue_phrases: Annotated[list[ShortText], Field(max_length=12)]


class ExplanationRubric(ContractModel):
    schema_version: Literal["explanation-rubric.v1"] = "explanation-rubric.v1"
    id: EntityId
    concept_id: EntityId
    prompt: LongText
    criteria: Annotated[list[RubricCriterion], Field(min_length=1, max_length=6)]
    max_confidence: Confidence = 0.6


class CriterionJudgment(ContractModel):
    criterion_id: EntityId
    status: CriterionStatus
    confidence: Confidence


class ExplanationJudgment(ContractModel):
    schema_version: Literal["explanation-judgment.v1"] = "explanation-judgment.v1"
    rubric_id: EntityId
    judge: JudgeKind
    evidence_kind: Literal["inference"] = "inference"
    judgment_scope: Literal["pedagogical"] = "pedagogical"
    judgments: Annotated[list[CriterionJudgment], Field(max_length=6)]


class ExplanationJudge(Protocol):
    def judge(self, rubric: ExplanationRubric, explanation: str) -> ExplanationJudgment: ...


DISTRIBUTION_EXPLANATION_RUBRIC = ExplanationRubric(
    id="rubric.distribution.explain",
    concept_id="concept.distribution",
    prompt="Explain why 2(x + 3) equals 2x + 6.",
    criteria=[
        RubricCriterion(
            id="multiplies_each_term",
            description="The outside factor multiplies every term inside the parentheses.",
            cue_phrases=["each term", "both terms", "every term", "the x and the 3", "both"],
        ),
        RubricCriterion(
            id="groups_as_repeated_addition",
            description="Connects 2(x + 3) to two groups of (x + 3).",
            cue_phrases=["two groups", "2 groups", "twice", "(x + 3) + (x + 3)", "x+3+x+3"],
        ),
        RubricCriterion(
            id="preserves_value",
            description="States the rewrite keeps the value the same.",
            cue_phrases=["same value", "equal", "equivalent", "doesn't change", "does not change"],
        ),
    ],
)


class KeywordExplanationJudge:
    """Marks a criterion ``met`` only when a cue phrase appears; absence stays ``unknown``.

    Missing keywords are not evidence that the reasoning is wrong, so this judge never
    returns ``not_met``.
    """

    def judge(self, rubric: ExplanationRubric, explanation: str) -> ExplanationJudgment:
        text = " ".join(explanation[:MAX_EXPLANATION_CHARS].lower().split())
        judgments = []
        for criterion in rubric.criteria:
            hit = any(" ".join(cue.lower().split()) in text for cue in criterion.cue_phrases)
            judgments.append(
                CriterionJudgment(
                    criterion_id=criterion.id,
                    status="met" if hit else "unknown",
                    confidence=rubric.max_confidence if hit else 0.0,
                )
            )
        return ExplanationJudgment(
            rubric_id=rubric.id, judge="deterministic_keyword", judgments=judgments
        )


def validate_judgment(rubric: ExplanationRubric, judgment: ExplanationJudgment) -> None:
    """Raise ``ValueError`` if a (possibly provider-proposed) judgment does not fit the rubric."""
    if judgment.rubric_id != rubric.id:
        raise ValueError("judgment refers to a different rubric")
    known = {criterion.id for criterion in rubric.criteria}
    seen: set[str] = set()
    for item in judgment.judgments:
        if item.criterion_id not in known:
            raise ValueError(f"unknown criterion {item.criterion_id}")
        if item.criterion_id in seen:
            raise ValueError(f"criterion {item.criterion_id} judged twice")
        if item.confidence > rubric.max_confidence:
            raise ValueError("confidence exceeds the rubric's limit")
        seen.add(item.criterion_id)
