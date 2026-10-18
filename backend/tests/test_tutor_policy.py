"""Unit tests for the deterministic policy, wording, persona phrasing and problem specs."""

import pytest

from app.db.seed import (
    EXPLANATION_PROBLEM_ID,
    FIXTURE_PROBLEM_ID,
    STRUCTURAL_TRANSFER_PROBLEM_ID,
    TRANSFER_PROBLEM_ID,
)
from app.pedagogy.messages import render_utterance
from app.pedagogy.persona import (
    APPEARANCES,
    COMFORT_OVERRIDES,
    PERSONALITIES,
    effective_personality,
    opener,
)
from app.pedagogy.policy import (
    Persona,
    WorkFacts,
    classify_work,
    grouping_mark,
    normalize,
    plan_check_in,
    plan_work,
)
from app.pedagogy.problems import (
    PROBLEMS,
    ProblemSpec,
    fresh_variant_reason,
    problem_spec,
)
from app.schemas.tutor import HypothesisView, ProblemView

FIXTURE = problem_spec(FIXTURE_PROBLEM_ID)
TRANSFER = problem_spec(TRANSFER_PROBLEM_ID)
STRUCTURAL = problem_spec(STRUCTURAL_TRANSFER_PROBLEM_ID)
EXPLANATION = problem_spec(EXPLANATION_PROBLEM_ID)


def view(spec: ProblemSpec, statement_object: str | None = "stmt-obj") -> ProblemView:
    return ProblemView(
        problem_id=spec.problem_id,
        attempt_id="attempt-1",
        statement=spec.statement,
        kind=spec.kind,
        concept_id=spec.concept_id,
        statement_object_id=statement_object,
    )


class TestClassifyWork:
    def test_expanded_distribution_step_is_valid(self) -> None:
        analysis = classify_work(FIXTURE, [], "2x + 6 = 14", "typed")
        assert analysis.classification == "valid_step"
        assert analysis.is_expanded_step is True
        assert analysis.verification is not None and analysis.verification.status == "valid"

    def test_other_equivalent_step_is_valid(self) -> None:
        analysis = classify_work(FIXTURE, [], "x + 3 = 7", "typed")
        assert analysis.classification == "valid_step"
        assert analysis.is_expanded_step is False

    def test_partial_distribution_is_distinct_from_other_invalid_steps(self) -> None:
        partial = classify_work(FIXTURE, [], "2x + 3 = 14", "typed")
        assert partial.classification == "partial_distribution"
        assert partial.verification is not None and partial.verification.status == "invalid"
        other = classify_work(FIXTURE, [], "2x + 3 = 15", "typed")
        assert other.classification == "invalid_step"

    def test_correct_value_with_checked_prior_step_has_reasoning(self) -> None:
        analysis = classify_work(FIXTURE, ["2x + 6 = 14"], "x = 4", "typed")
        assert analysis.classification == "solution_with_reasoning"

    def test_correct_value_alone_or_after_an_invalid_step_lacks_reasoning(self) -> None:
        alone = classify_work(FIXTURE, [], "x = 4", "typed")
        assert alone.classification == "solution_without_reasoning"
        assert alone.unresolved_step is None
        after_invalid = classify_work(FIXTURE, ["2x + 3 = 14"], "x = 4", "typed")
        assert after_invalid.classification == "solution_without_reasoning"
        assert after_invalid.unresolved_step == "2x + 3 = 14"

    def test_wrong_value_is_a_wrong_solution_not_an_invalid_step(self) -> None:
        analysis = classify_work(FIXTURE, [], "x = 5", "typed")
        assert analysis.classification == "wrong_solution"
        assert analysis.verification is not None
        assert analysis.verification.reason == "solution_differs"

    def test_uncheckable_input_is_unsupported_not_incorrect(self) -> None:
        analysis = classify_work(FIXTURE, [], "__import__('os')", "typed")
        assert analysis.classification == "unsupported"
        assert analysis.verification is not None and analysis.verification.status == "unknown"

    def test_unconfirmed_ink_is_never_assessed(self) -> None:
        analysis = classify_work(FIXTURE, [], "2x + 6 = 14", "unconfirmed_ink")
        assert analysis.classification == "unconfirmed_ink"
        assert analysis.verification is not None and analysis.verification.status == "unknown"

    def test_explanation_problem_text_is_an_explanation(self) -> None:
        analysis = classify_work(EXPLANATION, [], "because both terms", "typed")
        assert analysis.classification == "explanation"

    def test_structural_transfer_step_and_solution(self) -> None:
        step = classify_work(STRUCTURAL, [], "5 = 2z - 6 + 1", "typed")
        assert step.classification == "valid_step"
        solved = classify_work(STRUCTURAL, ["5 = 2z - 6 + 1"], "z = 5", "typed")
        assert solved.classification == "solution_with_reasoning"


def facts(**overrides: object) -> WorkFacts:
    values: dict[str, object] = {
        "turn_id": "turn-1",
        "spec": FIXTURE,
        "problem": view(FIXTURE),
        "analysis": classify_work(FIXTURE, [], "2x + 3 = 14", "typed"),
        "text": "2x + 3 = 14",
        "step_id": "step-1",
        "observation_ids": ("obs-1",),
        "attempt_hint_ids": (),
        "attempt_hint_levels": (),
        "expanded_seen": False,
    }
    values.update(overrides)
    return WorkFacts(**values)  # type: ignore[arg-type]


class TestCheckInPlan:
    def plan(self, energy: str | None, reminders: list[str] | None = None):
        return plan_check_in(
            turn_id="turn-1",
            spec=FIXTURE,
            problem=view(FIXTURE),
            energy=energy,  # type: ignore[arg-type]
            check_in_observation_id="obs-checkin",
            reminder_ids=reminders or [],
            persona=Persona(),
        )

    def test_tired_check_in_lightens_pace_and_proposes_session_context(self) -> None:
        plan = self.plan("tired")
        assert plan.pace == "lighter"
        assert plan.memory_hint == "session_tiredness"
        assert plan.local_source_ids == ["obs-checkin"]

    def test_ready_check_in_keeps_standard_pace_without_memory(self) -> None:
        plan = self.plan("ready")
        assert plan.pace == "standard"
        assert plan.memory_hint == "none"

    def test_check_in_never_discloses_the_answer_or_completed_step(self) -> None:
        plan = self.plan(None)
        assert {"x=4", "4=x", "2x+6=14", "2x+6"} <= set(plan.forbidden_disclosures)
        utterance = render_utterance(plan)
        assert "2(x + 3) = 14" in utterance
        for forbidden in plan.forbidden_disclosures:
            assert forbidden not in normalize(utterance)

    def test_returning_learner_is_told_about_earlier_assistance(self) -> None:
        plan = self.plan(None, reminders=["note-1"])
        assert plan.message_params["returning"] == "yes"
        assert "Last time" in render_utterance(plan)
        assert "note-1" in plan.required_evidence_ids


class TestWorkPlan:
    def test_partial_distribution_plans_a_grounded_diagnostic_hint(self) -> None:
        hypothesis = HypothesisView(
            id="hyp-1",
            label="Partial distribution",
            confidence=0.5,
            alternatives=["Copying slip"],
            status="tentative",
            source_ids=["step-1", "obs-1"],
        )
        plan = plan_work(facts(hypothesis=hypothesis), persona=Persona())
        assert plan.action_type == "diagnostic_hint"
        assert plan.hint_level == 1
        assert plan.hypothesis is hypothesis
        assert "hyp-1" in plan.required_evidence_ids
        assert "step-1" in plan.required_evidence_ids
        # The hint points at the grouping but completes neither the step nor the solution.
        utterance = render_utterance(plan)
        assert "every term" in utterance
        for forbidden in plan.forbidden_disclosures:
            assert forbidden not in normalize(utterance)
        assert {"x=4", "4=x", "2x+6=14", "2x+6"} <= set(plan.forbidden_disclosures)
        # A deterministic drawing proposal marks the parenthesized group.
        assert [a["tool"] for a in plan.drawing_actions] == ["highlight", "draw_shape"]
        assert plan.drawing_actions[0]["term"] == "(x + 3)"

    def test_repeated_partial_distribution_changes_representation_one_level_up(self) -> None:
        plan = plan_work(facts(attempt_hint_ids=("h1",), attempt_hint_levels=(1,)), Persona())
        assert plan.action_type == "change_representation"
        assert plan.representation == "groups_picture"
        assert plan.hint_level == 2
        assert "groups of" in render_utterance(plan)

    def test_valid_step_acknowledges_without_doing_the_next_step(self) -> None:
        analysis = classify_work(FIXTURE, [], "2x + 6 = 14", "typed")
        plan = plan_work(
            facts(analysis=analysis, text="2x + 6 = 14", expanded_seen=True), Persona()
        )
        assert plan.action_type == "step_feedback"
        assert plan.hint_level == 0
        assert plan.drawing_actions == []
        utterance = render_utterance(plan)
        # The learner produced the expansion, so naming it is no longer a disclosure.
        assert "2*x + 6 = 14" in utterance
        assert "x=4" not in set(plan.forbidden_disclosures) - {"x=4"}

    def test_correct_value_without_reasoning_asks_for_the_method(self) -> None:
        analysis = classify_work(FIXTURE, ["2x + 3 = 14"], "x = 4", "typed")
        plan = plan_work(facts(analysis=analysis, text="x = 4"), Persona())
        assert plan.action_type == "reasoning_check"
        assert "does work" in render_utterance(plan)

    def test_wrong_solution_suggests_substitution_not_the_answer(self) -> None:
        analysis = classify_work(FIXTURE, [], "x = 5", "typed")
        plan = plan_work(facts(analysis=analysis, text="x = 5"), Persona())
        assert plan.action_type == "solution_feedback"
        utterance = render_utterance(plan)
        assert "x = 5" in utterance
        assert "x=4" not in normalize(utterance)

    def test_unconfirmed_ink_asks_for_confirmation(self) -> None:
        analysis = classify_work(FIXTURE, [], "2x + 6 = 14", "unconfirmed_ink")
        plan = plan_work(facts(analysis=analysis, step_id=None, observation_ids=()), Persona())
        assert plan.action_type == "confirm_ink"
        assert plan.step_status == "unknown"

    def test_solved_independently_offers_the_fresh_transfer(self) -> None:
        analysis = classify_work(FIXTURE, ["2x + 6 = 14"], "x = 4", "typed")
        plan = plan_work(
            facts(
                analysis=analysis,
                text="x = 4",
                next_problem=view(TRANSFER, None),
                next_spec=TRANSFER,
            ),
            Persona(),
        )
        assert plan.action_type == "feedback_and_transfer"
        assert plan.current_problem is not None
        assert plan.current_problem.problem_id == TRANSFER_PROBLEM_ID
        # The fresh problem is posed unsolved: its answer and expansion stay hidden too.
        assert {"x=6", "3x-6=12", "3x-6"} <= set(plan.forbidden_disclosures)

    def test_solved_after_help_still_offers_transfer_and_notes_assistance(self) -> None:
        analysis = classify_work(FIXTURE, ["2x + 6 = 14"], "x = 4", "typed")
        plan = plan_work(
            facts(
                analysis=analysis,
                text="x = 4",
                attempt_hint_ids=("hint-1",),
                attempt_hint_levels=(1,),
                assessment_observation_id="obs-a",
                next_problem=view(TRANSFER, None),
                next_spec=TRANSFER,
            ),
            Persona(),
        )
        assert plan.action_type == "feedback_and_transfer"
        assert plan.memory_hint == "assisted_success_note"
        assert "hint-1" in plan.required_evidence_ids
        assert "obs-a" in plan.required_evidence_ids

    def test_last_problem_solved_wraps_up(self) -> None:
        analysis = classify_work(STRUCTURAL, ["5 = 2z - 6 + 1"], "z = 5", "typed")
        spec_view = view(STRUCTURAL)
        plan = plan_work(
            facts(
                spec=STRUCTURAL,
                problem=spec_view,
                analysis=analysis,
                text="z = 5",
                next_problem=None,
                next_spec=None,
            ),
            Persona(),
        )
        # After the structural transfer comes the explanation exercise; None means wrap up.
        assert plan.action_type in ("transfer_feedback_and_explain", "wrap_up")


class TestPersona:
    def test_three_appearances_five_ducks_three_comfort_overrides(self) -> None:
        assert APPEARANCES == ("animal", "older_adult", "younger_adult")
        assert PERSONALITIES == ("vincent", "zeeshan", "tony", "janelle", "mary")
        assert COMFORT_OVERRIDES == ("none", "neutral_supportive", "reduced_sass")

    @pytest.mark.parametrize("personality", PERSONALITIES)
    @pytest.mark.parametrize("tone", ("neutral", "correction", "success", "support"))
    def test_every_personality_and_tone_is_worded_and_kind(self, personality, tone) -> None:
        # All 12 combinations produce wording; none demeans the learner.
        text = opener(personality, "none", tone)  # type: ignore[arg-type]
        assert text == text.strip() or text.endswith(" ")
        lowered = text.lower()
        for demeaning in ("stupid", "wrong again", "bad job", "you failed"):
            assert demeaning not in lowered

    def test_comfort_override_is_immediate_and_separate(self) -> None:
        assert effective_personality("zeeshan", "reduced_sass") == "vincent"
        assert effective_personality("tony", "neutral_supportive") == "janelle"
        assert effective_personality("tony", "reduced_sass") == "tony"
        assert effective_personality("janelle", "none") == "janelle"


class TestFreshTransfer:
    def test_builtin_transfers_are_fresh(self) -> None:
        assert fresh_variant_reason(FIXTURE, TRANSFER) is None
        assert fresh_variant_reason(TRANSFER, STRUCTURAL) is None
        assert fresh_variant_reason(FIXTURE, STRUCTURAL) is None

    def test_same_problem_is_not_fresh(self) -> None:
        assert fresh_variant_reason(FIXTURE, FIXTURE) == "same_problem"

    def test_renaming_the_variable_is_not_fresh(self) -> None:
        renamed = ProblemSpec(
            problem_id="problem.renamed",
            statement="2(y + 3) = 14",
            kind="transfer",
            concept_id=FIXTURE.concept_id,
            step_concept_id=FIXTURE.step_concept_id,
            variable="y",
            solution="4",
        )
        assert fresh_variant_reason(FIXTURE, renamed) == "renamed_only"

    def test_non_transfer_is_not_a_transfer_opportunity(self) -> None:
        assert fresh_variant_reason(FIXTURE, EXPLANATION) == "not_a_transfer_problem"

    def test_structural_transfer_solution_matches_contract(self) -> None:
        # VAL-MATH-002: 5 = 2(z - 3) + 1 expands to 5 = 2z - 6 + 1 and solves to z = 5.
        assert STRUCTURAL.expanded_step == "5 = 2z - 6 + 1"
        assert STRUCTURAL.solution == "5"
        assert STRUCTURAL.variable == "z"


def test_grouping_mark_marks_the_parenthesized_group_deterministically() -> None:
    actions = grouping_mark(FIXTURE, "stmt-obj")
    assert actions[0]["tool"] == "highlight"
    assert actions[0]["target_object_id"] == "stmt-obj"
    assert actions[1]["shape"] == "bracket"
    # "2(x + 3) = 14": the group spans characters 1..8 of the fixed layout.
    assert actions[1]["start"]["x"] == 80 + 1 * 26
    assert actions[1]["end"]["x"] == 80 + 8 * 26


def test_every_seeded_problem_has_a_spec() -> None:
    for problem_id in (
        FIXTURE_PROBLEM_ID,
        TRANSFER_PROBLEM_ID,
        STRUCTURAL_TRANSFER_PROBLEM_ID,
        EXPLANATION_PROBLEM_ID,
    ):
        assert problem_id in PROBLEMS
