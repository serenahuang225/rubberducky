import pytest
from pydantic import ValidationError

from app.verification import (
    DISTRIBUTION_EXPLANATION_RUBRIC,
    ExplanationJudgment,
    KeywordExplanationJudge,
    check_solution,
    validate_judgment,
)
from app.verification.explanation import CriterionJudgment

RUBRIC = DISTRIBUTION_EXPLANATION_RUBRIC


def statuses(judgment: ExplanationJudgment) -> dict[str, str]:
    return {item.criterion_id: item.status for item in judgment.judgments}


def test_keyword_judge_marks_cues_met_and_leaves_absence_unknown() -> None:
    judgment = KeywordExplanationJudge().judge(
        RUBRIC, "The 2 multiplies both terms, so it is like two groups of x + 3."
    )
    assert statuses(judgment) == {
        "multiplies_each_term": "met",
        "groups_as_repeated_addition": "met",
        "preserves_value": "unknown",
    }
    assert judgment.evidence_kind == "inference"
    assert judgment.judgment_scope == "pedagogical"
    assert all(item.confidence <= RUBRIC.max_confidence for item in judgment.judgments)
    validate_judgment(RUBRIC, judgment)


def test_keyword_judge_never_returns_not_met() -> None:
    judgment = KeywordExplanationJudge().judge(RUBRIC, "I just know it")
    assert set(statuses(judgment).values()) == {"unknown"}


def test_code_like_explanation_is_only_text() -> None:
    judgment = KeywordExplanationJudge().judge(RUBRIC, "__import__('os').system('rm -rf /')" * 50)
    assert set(statuses(judgment).values()) == {"unknown"}


def test_correct_answer_and_rubric_are_independent() -> None:
    math = check_solution("2(x + 3) = 14", "x = 4")
    judgment = KeywordExplanationJudge().judge(RUBRIC, "I guessed")
    assert math.status == "valid" and math.judgment_scope == "mathematical"
    assert "met" not in statuses(judgment).values()


@pytest.mark.parametrize(
    ("judgment", "message"),
    [
        (
            ExplanationJudgment(rubric_id="rubric.other", judge="provider", judgments=[]),
            "different rubric",
        ),
        (
            ExplanationJudgment(
                rubric_id=RUBRIC.id,
                judge="provider",
                judgments=[CriterionJudgment(criterion_id="mastery", status="met", confidence=0.5)],
            ),
            "unknown criterion",
        ),
        (
            ExplanationJudgment(
                rubric_id=RUBRIC.id,
                judge="provider",
                judgments=[
                    CriterionJudgment(
                        criterion_id="multiplies_each_term", status="met", confidence=0.99
                    )
                ],
            ),
            "confidence",
        ),
        (
            ExplanationJudgment(
                rubric_id=RUBRIC.id,
                judge="provider",
                judgments=[
                    CriterionJudgment(criterion_id="preserves_value", status="met", confidence=0.5),
                    CriterionJudgment(
                        criterion_id="preserves_value", status="not_met", confidence=0.5
                    ),
                ],
            ),
            "twice",
        ),
    ],
)
def test_provider_judgments_are_validated(judgment: ExplanationJudgment, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_judgment(RUBRIC, judgment)


def test_judgment_contract_rejects_other_evidence_kinds() -> None:
    with pytest.raises(ValidationError):
        ExplanationJudgment.model_validate(
            {
                "rubric_id": RUBRIC.id,
                "judge": "provider",
                "evidence_kind": "verified_assessment",
                "judgments": [],
            }
        )
