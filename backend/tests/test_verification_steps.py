import pytest

import app.verification.verifier as verifier_module
from app.verification import WorkSource, check_solution, check_step


@pytest.mark.parametrize(
    ("reference", "candidate", "status", "reason"),
    [
        ("2(x + 3) = 14", "2x + 6 = 14", "valid", "equivalent"),
        ("2(x + 3) = 14", "2x + 3 = 14", "invalid", "not_equivalent"),
        ("2(x + 3) = 14", "x + 3 = 7", "valid", "equivalent"),
        ("2(x + 3) = 14", "2x = 8", "valid", "equivalent"),
        ("2(x + 3) = 14", "14 = 2x + 6", "valid", "equivalent"),
        ("2(x + 3) = 14", "x = 4", "valid", "equivalent"),
        ("2(x + 3) = 14", "x = 5", "invalid", "not_equivalent"),
        ("5 = 2(z - 3) + 1", "5 = 2z - 6 + 1", "valid", "equivalent"),
        ("5 = 2(z - 3) + 1", "5 = 2z - 3 + 1", "invalid", "not_equivalent"),
        ("5 = 2(z - 3) + 1", "10 = 2z", "valid", "equivalent"),
        ("3(y - 2) = 12", "3y - 6 = 12", "valid", "equivalent"),
        ("3(y - 2) = 12", "3y - 2 = 12", "invalid", "not_equivalent"),
        ("-4(a + 1) = 8", "-4a - 4 = 8", "valid", "equivalent"),
        ("-4(a + 1) = 8", "-4a + 4 = 8", "invalid", "not_equivalent"),
        ("0.5(4x + 2) = 5", "2x + 1 = 5", "valid", "equivalent"),
        ("x/2 + 1 = 4", "x + 2 = 8", "valid", "equivalent"),
        ("2(x + 3) = 2x + 6", "6 = 6", "valid", "equivalent"),
        ("2(x + 3) = 2x + 5", "6 = 5", "valid", "equivalent"),
        ("2(x + 3) = 2x + 6", "x = 0", "invalid", "not_equivalent"),
        ("2(x + 3) = 14", "2z + 6 = 14", "invalid", "different_variable"),
        ("2(x + 3) = 14", "2x + 6", "unknown", "kind_mismatch"),
        ("2(x + 3)", "2x + 6", "valid", "equivalent"),
        ("2(x + 3)", "2x + 3", "invalid", "not_equivalent"),
        ("2(x + y)", "2x + 2y", "valid", "equivalent"),
        ("-(x - 5)", "5 - x", "valid", "equivalent"),
        ("2(x + 3)", "2x + 6 = 0", "unknown", "kind_mismatch"),
        ("x + y = 2", "y = 2 - x", "unknown", "reference_not_checkable"),
        ("2(x + 3) = 14", "x + y = 7", "unknown", "candidate_not_checkable"),
    ],
)
def test_next_step_equivalence(reference: str, candidate: str, status: str, reason: str) -> None:
    result = check_step(reference, candidate)
    assert (result.status, result.reason) == (status, reason)
    assert result.judgment_scope == "mathematical"


def test_equation_step_reports_solution_sets() -> None:
    result = check_step("2(x + 3) = 14", "2x + 3 = 14")
    assert result.reference_solution is not None and result.candidate_solution is not None
    expected = {"kind": "single", "variable": "x", "value": "4"}
    assert result.reference_solution.model_dump() == expected
    assert result.candidate_solution.value == "11/2"


@pytest.mark.parametrize(
    ("equation", "answer", "status", "reason"),
    [
        ("2(x + 3) = 14", "x = 4", "valid", "solution_matches"),
        ("2(x + 3) = 14", "4 = x", "valid", "solution_matches"),
        ("2(x + 3) = 14", "4", "valid", "solution_matches"),
        ("2(x + 3) = 14", "8/2", "valid", "solution_matches"),
        ("2(x + 3) = 14", "x = 5.5", "invalid", "solution_differs"),
        ("5 = 2(z - 3) + 1", "z = 5", "valid", "solution_matches"),
        ("5 = 2(z - 3) + 1", "x = 5", "invalid", "different_variable"),
        ("3x - 2 = 12", "x = 14/3", "valid", "solution_matches"),
        ("2(x + 3) = 2x + 6", "x = 1", "invalid", "solution_differs"),
        ("2(x + 3) = 2x + 5", "x = 1", "invalid", "solution_differs"),
        ("2(x + 3) = 14", "2x = 8", "unknown", "not_solved_form"),
        ("2(x + 3) = 14", "x", "unknown", "not_solved_form"),
        ("2(x + 3) = 14", "x = 1/0", "unknown", "candidate_not_checkable"),
        ("2(x + 3)", "x = 4", "unknown", "reference_not_checkable"),
    ],
)
def test_solution_checks(equation: str, answer: str, status: str, reason: str) -> None:
    result = check_solution(equation, answer)
    assert (result.status, result.reason) == (status, reason)


def test_non_equation_reference_is_typed_unsupported() -> None:
    result = check_solution("2(x + 3)", "x = 4")
    assert (result.reference.status, result.reference.reason) == ("unsupported", "not_an_equation")


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (WorkSource(author_role="student", input_mode="unconfirmed_ink"), "unconfirmed_ink"),
        (WorkSource(author_role="tutor", input_mode="typed"), "tutor_authored"),
        (WorkSource(author_role="tutor", input_mode="confirmed_ink"), "tutor_authored"),
    ],
)
def test_unconfirmed_ink_and_tutor_work_are_not_assessed(
    source: WorkSource, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed_texts: list[str] = []
    original = verifier_module.parse_math

    def recording(text: str, bounds: verifier_module.VerificationBounds) -> verifier_module.Parsed:
        parsed_texts.append(text)
        return original(text, bounds)

    monkeypatch.setattr(verifier_module, "parse_math", recording)
    for result in (
        check_step("2(x + 3) = 14", "x = 4", source),
        check_solution("2(x + 3) = 14", "x = 4", source),
    ):
        assert result.status == "unknown"
        assert result.reason == "candidate_not_checkable"
        assert (result.candidate.status, result.candidate.reason) == ("not_assessable", reason)
    assert "x = 4" not in parsed_texts


def test_confirmed_ink_from_student_is_assessed() -> None:
    source = WorkSource(author_role="student", input_mode="confirmed_ink")
    assert check_solution("2(x + 3) = 14", "x = 4", source).status == "valid"


def test_results_round_trip_as_versioned_contracts() -> None:
    result = check_step("2(x + 3) = 14", "2x + 6 = 14")
    restored = type(result).model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.schema_version == "verification-result.v1"
    assert restored.bounds_version == "verification-bounds.v1"
