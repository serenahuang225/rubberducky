"""Evidence-based pedagogical agency over the real API (VAL-TEACH-004 to VAL-TEACH-008).

Covers a correct value with a questionable method, tentative hypotheses that admit
counterevidence, "I don't know" / "just tell me", repeated difficulty, fading support and
waiting that creates no evidence. Everything runs through the real coordinator on a
migrated file-backed SQLite database with the deterministic mock provider.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.clock import utc_now
from app.db.database import Database
from app.db.models import (
    BKTCountedOpportunityRow,
    EvidenceLinkRow,
    HintRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SessionRow,
    TutorTurnRow,
)
from app.inference.providers import MockTutorProvider, ProviderLabel
from app.pedagogy.policy import Persona, plan_work
from app.tracing.contracts import IneligibleReason
from tests.conftest import bootstrap
from tests.test_tutor_turns import (
    DOUBLE_LABEL,
    LINEAR,
    check_in,
    key,
    mastery,
    post_turn,
    start_session,
    table_counts,
    work,
)

METHOD_SLIP = "x = 4 because I multiplied 2 by x but left 3 unchanged"
SHAMING = ("wrong", "incorrect", "failed", "bad at", "slow", "dumb", "always")


def help_turn(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    revision: int,
    mode: str = "hint",
    turn_key: str | None = None,
):
    return post_turn(
        client,
        headers,
        session_id,
        "help",
        {"expected_revision": revision, "mode": mode},
        turn_key or key("help"),
    )


def counted_opportunities(database: Database, learner_id: str) -> int:
    with database.transaction() as db:
        return db.execute(
            select(func.count())
            .select_from(BKTCountedOpportunityRow)
            .where(BKTCountedOpportunityRow.learner_id == learner_id)
        ).scalar_one()


def assert_not_shaming(text: str) -> None:
    lowered = text.lower()
    for word in SHAMING:
        assert word not in lowered, f"{word!r} in {text!r}"


class TestCorrectValueWithQuestionableReasoning:
    """VAL-TEACH-004."""

    def test_correct_value_with_a_method_slip_gets_a_targeted_check_not_credit(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, METHOD_SLIP, 1)
        student = result["student_input"]

        # The verifier and the pedagogical reading are separate outcomes.
        assert student["verification"]["status"] == "valid"
        assert student["classification"] == "solution_with_questionable_reasoning"
        assessment = student["reasoning_assessment"]
        assert assessment["status"] == "questionable"
        assert assessment["judgment_scope"] == "pedagogical"
        assert assessment["evidence_kind"] == "inference"
        assert assessment["pattern"] == "second_term_unchanged"
        assert assessment["confidence"] < 0.8
        assert "left 3 unchanged" in assessment["explanation_text"]

        # A targeted question names the claim and the method; it never says the value is wrong.
        assert result["action_type"] == "reasoning_check"
        assert "x = 4" in result["utterance"]
        assert "3" in result["utterance"]
        assert_not_shaming(result["utterance"])
        assert result["current_problem"]["statement"] == "2(x + 3) = 14"

        # No independent success: not assessed as independent, not eligible, nothing counted.
        assert student["assessment_independent"] is False
        (note,) = student["eligibility"]
        assert note["eligible"] is False
        assert note["reason"] == "independent_reasoning_missing"
        assert note["assisted"] is False
        assert mastery(database, learner_id, LINEAR) is None
        assert counted_opportunities(database, learner_id) == 0
        assert result["student_input"]["step_id"] in result["evidence_ids"]

    def test_a_method_that_checks_out_is_not_questioned(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        work(client, headers, session_id, "2x + 6 = 14", 1)
        solved = work(client, headers, session_id, "x = 4 because I multiplied 2 by x and 3", 2)
        assert solved["student_input"]["classification"] == "solution_with_reasoning"
        assert solved["student_input"]["reasoning_assessment"] is None
        assert solved["student_input"]["assessment_independent"] is True

    def test_resolving_the_reasoning_stays_assisted_because_the_check_pointed_at_it(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        checked = work(client, headers, session_id, METHOD_SLIP, 1)
        assert checked["hint_level"] == 1 and checked["hint_id"]
        fixed = work(client, headers, session_id, "2x + 6 = 14", 2)
        assert fixed["student_input"]["classification"] == "valid_step"
        solved = work(client, headers, session_id, "x = 4", 3)
        student = solved["student_input"]
        assert student["classification"] == "solution_with_reasoning"
        # The targeted question named the method, so this success is honestly assisted.
        assert student["assessment_independent"] is False
        (note,) = student["eligibility"]
        assert note["assisted"] is True
        assert note["reason"] != "independent_reasoning_missing"
        assert counted_opportunities(database, learner_id) == 0

    def test_eligibility_reason_distinguishes_missing_reasoning_from_assisted_work(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        bare = work(client, headers, session_id, "x = 4", 1)
        (bare_note,) = bare["student_input"]["eligibility"]
        assert bare_note["assisted"] is False
        assert bare_note["reason"] == "independent_reasoning_missing"

        _, other = bootstrap(client, "Second learner")
        other_session = start_session(client, other)
        check_in(client, other, other_session)
        work(client, other, other_session, "2x + 3 = 14", 1)
        hinted = work(client, other, other_session, "x = 4", 2)
        (hinted_note,) = hinted["student_input"]["eligibility"]
        assert hinted_note["assisted"] is True
        assert hinted_note["reason"] in ("hint_in_attempt", "assisted")
        assert hinted_note["reason"] != "independent_reasoning_missing"

    def test_the_new_reason_is_part_of_the_published_contract(self) -> None:
        assert "independent_reasoning_missing" in IneligibleReason.__args__  # type: ignore[attr-defined]


class TestTentativeHypothesesAndCounterevidence:
    """VAL-TEACH-005."""

    def _first_slip(self, client: TestClient, headers: dict[str, str]) -> tuple[str, dict]:
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        return session_id, work(client, headers, session_id, "2x + 3 = 14", 1)

    def test_one_first_term_step_is_a_tentative_hypothesis_with_alternatives(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        _, result = self._first_slip(client, headers)
        hypothesis = result["hypothesis"]
        assert hypothesis["status"] == "tentative"
        assert hypothesis["confidence"] <= 0.6
        assert hypothesis["alternatives"], "a plausible alternative such as a copying slip"
        assert any("copy" in alternative.lower() for alternative in hypothesis["alternatives"])
        assert hypothesis["source_ids"]
        assert hypothesis["contradicting_source_ids"] == []
        assert hypothesis["substantive_counterevidence"] is False
        assert hypothesis["id"] in result["evidence_ids"]
        # Public wording stays tentative and makes no claim about the person.
        utterance = result["utterance"].lower()
        for banned in ("you always", "you are a", "learning style", "disab", "you're bad"):
            assert banned not in utterance
        assert_not_shaming(result["utterance"])
        assert result["decision_justification"]
        assert len(result["decision_justification"]) <= 200

    def _slip_fix_and_solve(
        self, client: TestClient, headers: dict[str, str]
    ) -> tuple[str, dict, int]:
        """First problem: a slip, a hinted fix and a supported solution. Returns the next one."""
        session_id, first = self._first_slip(client, headers)
        work(client, headers, session_id, "2x + 6 = 14", 2)
        solved = work(client, headers, session_id, "x = 4", 3)
        assert solved["current_problem"]["statement"] == "3(x - 2) = 12"
        return session_id, first, 4

    def test_unassisted_full_distribution_is_counterevidence_that_changes_the_next_move(
        self, client: TestClient, database: Database
    ) -> None:
        _, headers = bootstrap(client)
        session_id, first, revision = self._slip_fix_and_solve(client, headers)
        _, headers_control = bootstrap(client, "Control learner")
        control_session, _, control_revision = self._slip_fix_and_solve(client, headers_control)

        # Same slip on the new problem; only the learner's history differs.
        control = work(client, headers_control, control_session, "3x - 2 = 12", control_revision)
        assert control["action_type"] == "diagnostic_hint"
        assert control["representation"] == "outside_factor"

        proved = work(client, headers, session_id, "3x - 6 = 12", revision)
        assert proved["student_input"]["classification"] == "valid_step"
        assert proved["hypothesis"]["contradicting_source_ids"]
        again = work(client, headers, session_id, "3x - 2 = 12", revision + 1)
        hypothesis = again["hypothesis"]
        assert hypothesis["substantive_counterevidence"] is True
        assert hypothesis["confidence"] < first["hypothesis"]["confidence"]
        assert hypothesis["alternatives"] and hypothesis["status"] == "tentative"
        # The intervention differs: a copy check instead of re-teaching the grouping.
        assert again["action_type"] == "diagnostic_hint"
        assert again["representation"] == "copy_check"
        assert again["utterance"] != control["utterance"]
        assert "copy" in again["utterance"].lower() or "compare" in again["utterance"].lower()
        assert_not_shaming(again["utterance"])
        assert set(hypothesis["contradicting_source_ids"]) <= set(again["evidence_ids"])
        with database.transaction() as db:
            polarities = set(
                db.execute(
                    select(EvidenceLinkRow.polarity).where(
                        EvidenceLinkRow.hypothesis_id == hypothesis["id"]
                    )
                ).scalars()
            )
        assert polarities == {"supports", "contradicts"}

    def test_a_step_fixed_after_a_hint_is_only_weak_counterevidence(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id, first = self._first_slip(client, headers)
        fixed = work(client, headers, session_id, "2x + 6 = 14", 2)
        hypothesis = fixed["hypothesis"]
        assert hypothesis["contradicting_source_ids"]
        assert hypothesis["substantive_counterevidence"] is False
        assert hypothesis["confidence"] < first["hypothesis"]["confidence"]
        # Paired with an unaffected learner: a repeated slip still escalates the scaffold.
        _, headers_control = bootstrap(client, "Control learner")
        control_session, _ = self._first_slip(client, headers_control)
        control_second = work(client, headers_control, control_session, "2x + 3 = 14", 2)
        assert control_second["action_type"] == "change_representation"

    def test_a_hypothesis_is_not_promoted_to_a_label_by_repetition(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id, _ = self._first_slip(client, headers)
        revision = 2
        for _ in range(3):
            result = work(client, headers, session_id, "2x + 3 = 14", revision)
            revision += 1
        assert result["hypothesis"]["status"] == "tentative"
        assert result["hypothesis"]["confidence"] <= 0.8
        assert result["hypothesis"]["alternatives"]
        with database.transaction() as db:
            rows = (
                db.execute(
                    select(MisconceptionHypothesisRow).where(
                        MisconceptionHypothesisRow.learner_id == learner_id
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1


class TestNotKnowingAndExplanationRequests:
    """VAL-TEACH-006."""

    def _session(self, client: TestClient) -> tuple[str, str, dict[str, str]]:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        return learner_id, session_id, headers

    def test_i_dont_know_is_acknowledged_with_a_smaller_scaffold(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, session_id, headers = self._session(client)
        before = table_counts(database, learner_id)
        result = work(client, headers, session_id, "I don't know", 1)
        assert result["student_input"]["classification"] == "not_sure"
        assert result["action_type"] == "smaller_scaffold"
        assert result["hint_level"] == 1
        assert result["answer_revealed"] is False
        assert "outside" in result["utterance"].lower() or "2" in result["utterance"]
        assert "2x + 6" not in result["utterance"] and "x = 4" not in result["utterance"]
        assert result["expected_student_action"]
        assert_not_shaming(result["utterance"])
        # Not knowing is a self-report, not a step, an assessment or a mistake.
        after = table_counts(database, learner_id)
        assert after["steps"] == before["steps"]
        assert after["assessments"] == before["assessments"]
        assert after["hints"] == before["hints"] + 1
        assert mastery(database, learner_id, LINEAR) is None
        with database.transaction() as db:
            observation = db.execute(
                select(ObservationRow).where(ObservationRow.source_type == "help_request")
            ).scalar_one()
        assert observation.evidence_kind == "self_report"
        assert observation.correct is None

    def test_just_tell_me_gets_a_concise_explanation_and_a_learner_action(
        self, client: TestClient, database: Database
    ) -> None:
        _learner_id, session_id, headers = self._session(client)
        work(client, headers, session_id, "I don't know", 1)
        told = work(client, headers, session_id, "just tell me", 2)
        assert told["student_input"]["classification"] == "explain_request"
        assert told["action_type"] == "explain_on_request"
        # Concise, concrete, honest about what it shows.
        assert len(told["utterance"]) <= 600
        assert "2x + 6 = 14" in told["utterance"]
        assert told["answer_revealed"] is True
        assert told["hint_level"] >= 4
        assert told["expected_student_action"]
        assert told["utterance"].rstrip().endswith("?") or "Type" in told["utterance"]
        assert "x = 4" not in told["utterance"], "the final value is still the learner's step"
        # The disclosure matches the persisted hint row.
        with database.transaction() as db:
            hint = db.execute(select(HintRow).where(HintRow.id == told["hint_id"])).scalar_one()
        assert hint.answer_revealed is True
        assert hint.level == told["hint_level"]

    def test_success_after_an_explanation_remains_assisted(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, session_id, headers = self._session(client)
        told = work(client, headers, session_id, "I don't know, just tell me", 1)
        assert told["action_type"] == "explain_on_request"
        copied = work(client, headers, session_id, "2x + 6 = 14", 2)
        assert copied["student_input"]["classification"] == "valid_step"
        solved = work(client, headers, session_id, "x = 4", 3)
        student = solved["student_input"]
        assert student["classification"] == "solution_with_reasoning"
        assert student["assessment_independent"] is False
        (note,) = student["eligibility"]
        assert note["assisted"] is True and note["eligible"] is False
        assert counted_opportunities(database, learner_id) == 0
        assert mastery(database, learner_id, LINEAR) is None

    def test_help_button_works_without_any_timer_and_is_idempotent(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, session_id, headers = self._session(client)
        response = help_turn(client, headers, session_id, 1, turn_key="help-once")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "committed"
        assert result["student_input"]["input_mode"] == "help_button"
        assert result["action_type"] == "smaller_scaffold"
        assert result["answer_revealed"] is False
        replay = help_turn(client, headers, session_id, 1, turn_key="help-once").json()
        assert replay["replayed"] is True and replay["turn_id"] == result["turn_id"]
        assert table_counts(database, learner_id)["hints"] == 1
        stale = help_turn(client, headers, session_id, 1)
        assert stale.status_code == 409

    def test_help_can_ask_for_an_explanation_directly(self, client: TestClient) -> None:
        _, session_id, headers = self._session(client)
        result = help_turn(client, headers, session_id, 1, mode="explain").json()
        assert result["action_type"] == "explain_on_request"
        assert result["answer_revealed"] is True

    def test_a_draft_that_shows_a_step_without_disclosure_is_rejected(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        learner_id, session_id, headers = self._session(client)
        mock = MockTutorProvider()

        class Double:
            def label(self) -> ProviderLabel:
                return DOUBLE_LABEL

            def draft(self, inputs):
                return mock.draft(inputs).model_copy(update={"answer_revealed": False})

        monkeypatch.setattr("app.tutor.coordinator.get_provider", lambda settings: Double())
        before = table_counts(database, learner_id)
        response = post_turn(
            client,
            headers,
            session_id,
            "work",
            {"expected_revision": 1, "text": "just tell me"},
            key("undisclosed"),
        )
        result = response.json()
        assert result["status"] == "rejected"
        assert "disclosure_not_marked" in {r["code"] for r in result["rejections"]}
        assert table_counts(database, learner_id)["hints"] == before["hints"]


class TestRepeatedDifficultyAndFadingSupport:
    """VAL-TEACH-007."""

    def test_repeated_difficulty_changes_representation_each_time(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        moves = []
        for revision in range(1, 5):
            moves.append(work(client, headers, session_id, "2x + 3 = 14", revision))
        assert [m["action_type"] for m in moves] == [
            "diagnostic_hint",
            "change_representation",
            "change_representation",
            "explain_on_request",
        ]
        assert [m["representation"] for m in moves] == [
            "outside_factor",
            "groups_picture",
            "number_case",
            "worked_step",
        ]
        assert [m["hint_level"] for m in moves] == [1, 2, 3, 4]
        assert len({m["utterance"] for m in moves}) == 4, "no hint is recycled"
        assert len({m["hint_id"] for m in moves}) == 4
        for move in moves:
            assert_not_shaming(move["utterance"])
            assert move["utterance"]
            assert move["decision_justification"]
        # Changed prerequisite/grouping work is shown on the board, not just in words.
        assert any(d["tool"] == "add_math" for d in moves[1]["drawings"])
        assert moves[2]["target_concept_ids"] != moves[0]["target_concept_ids"]
        assert moves[3]["answer_revealed"] is True
        # Each rung cites the learner's own sources.
        for move in moves:
            assert move["student_input"]["step_id"] in move["evidence_ids"]
        with database.transaction() as db:
            levels = sorted(
                db.execute(select(HintRow.level).where(HintRow.learner_id == learner_id)).scalars()
            )
        assert levels == [1, 2, 3, 4]

    def test_after_the_explanation_the_ask_shrinks_instead_of_repeating(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        for revision in range(1, 5):
            work(client, headers, session_id, "2x + 3 = 14", revision)
        after = work(client, headers, session_id, "2x + 3 = 14", 5)
        assert after["action_type"] == "smaller_scaffold"
        assert after["representation"] == "next_step"
        assert after["answer_revealed"] is False

    @pytest.mark.parametrize("personality", ["gentle", "matter_of_fact", "playful", "mildly_sassy"])
    def test_representation_change_is_respectful_in_every_personality(
        self, client: TestClient, personality: str
    ) -> None:
        _, headers = bootstrap(client)
        client.put(
            "/me/tutor-configuration",
            json={"appearance": "animal", "personality": personality},
            headers=headers,
        )
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        for revision in range(1, 4):
            result = work(client, headers, session_id, "2x + 3 = 14", revision)
            assert_not_shaming(result["utterance"])
        assert result["action_type"] == "change_representation"

    def test_supported_success_is_followed_by_a_move_that_reduces_support(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        work(client, headers, session_id, "2x + 3 = 14", 1)
        work(client, headers, session_id, "2x + 3 = 14", 2)
        step = work(client, headers, session_id, "2x + 6 = 14", 3)
        assert step["support_change"] == "none"
        solved = work(client, headers, session_id, "x = 4", 4)
        # The supported success stays assisted, yet the next problem starts with less help.
        assert solved["student_input"]["assessment_independent"] is False
        assert solved["support_change"] == "reduced"
        assert solved["current_problem"] is not None
        assert solved["current_problem"]["statement"] != "2(x + 3) = 14"
        assert "ask" in solved["utterance"].lower()
        fresh = work(client, headers, session_id, "I don't know", 5)
        # A fresh attempt begins on the lowest rung again; the old highest level is not carried.
        assert fresh["hint_level"] == 1
        assert fresh["action_type"] == "smaller_scaffold"
        assert counted_opportunities(database, learner_id) == 0


class TestPolicyUnits:
    def test_explain_rung_is_only_reached_after_scaffolds_or_when_asked(self) -> None:
        from app.pedagogy.policy import classify_work
        from tests.test_tutor_policy import FIXTURE, facts

        analysis = classify_work(FIXTURE, [], "just tell me", "typed")
        assert analysis.classification == "explain_request"
        plan = plan_work(facts(analysis=analysis, text="just tell me"), Persona())
        assert plan.action_type == "explain_on_request"
        assert plan.reveal_allowed is True
        plan_not_sure = plan_work(
            facts(analysis=classify_work(FIXTURE, [], "idk", "typed"), text="idk"), Persona()
        )
        assert plan_not_sure.action_type == "smaller_scaffold"
        assert plan_not_sure.reveal_allowed is False


class TestWaitPreferenceAndStillThinking:
    """VAL-TEACH-008."""

    @pytest.fixture
    def clock(self, monkeypatch: pytest.MonkeyPatch):
        state = {"now": utc_now()}
        monkeypatch.setattr("app.api.wait.utc_now", lambda: state["now"])
        return state

    def test_preference_defaults_and_is_settable_within_bounds(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        default = client.get("/me/wait-preference", headers=headers).json()
        assert default["source"] == "default"
        assert default["wait_seconds"] == default["default_seconds"]
        saved = client.put("/me/wait-preference", json={"wait_seconds": 90}, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["wait_seconds"] == 90 and saved.json()["source"] == "preference"
        assert client.get("/me/wait-preference", headers=headers).json()["wait_seconds"] == 90
        for bad in (0, 4, 301, -1, 1.5, "soon", None):
            response = client.put(
                "/me/wait-preference", json={"wait_seconds": bad}, headers=headers
            )
            assert response.status_code == 422, bad
        assert client.get("/me/wait-preference", headers=headers).json()["wait_seconds"] == 90

    def test_quiet_hint_becomes_available_only_after_the_chosen_wait(
        self, client: TestClient, clock: dict
    ) -> None:
        _, headers = bootstrap(client)
        client.put("/me/wait-preference", json={"wait_seconds": 60}, headers=headers)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        state = client.get(f"/sessions/{session_id}/wait", headers=headers).json()
        assert state["wait_seconds"] == 60 and state["wait_source"] == "preference"
        assert state["proactive_prompt"] == "none"
        assert state["silence_interpretation"] == "missing_evidence"
        assert state["quiet_hint_available"] is False
        clock["now"] = utc_now() + timedelta(seconds=30)
        assert (
            client.get(f"/sessions/{session_id}/wait", headers=headers).json()[
                "quiet_hint_available"
            ]
            is False
        )
        clock["now"] = utc_now() + timedelta(seconds=75)
        late = client.get(f"/sessions/{session_id}/wait", headers=headers).json()
        assert late["quiet_hint_available"] is True
        assert late["next_hint_level"] == 1

    def test_long_silence_creates_no_evidence_prompt_or_mastery_change(
        self, client: TestClient, database: Database, clock: dict
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        work(client, headers, session_id, "2x + 6 = 14", 1)
        before = table_counts(database, learner_id)
        mastery_before = mastery(database, learner_id, LINEAR)
        with database.transaction() as db:
            revision_before = db.get(SessionRow, session_id).revision
        for minutes in (1, 5, 20, 60):
            clock["now"] = utc_now() + timedelta(minutes=minutes)
            state = client.get(f"/sessions/{session_id}/wait", headers=headers).json()
            assert state["quiet_hint_available"] is True
            assert state["proactive_prompt"] == "none"
        assert table_counts(database, learner_id) == before
        assert mastery(database, learner_id, LINEAR) == mastery_before
        with database.transaction() as db:
            assert db.get(SessionRow, session_id).revision == revision_before
            assert (
                db.execute(
                    select(func.count())
                    .select_from(ObservationRow)
                    .where(ObservationRow.source_type.in_(("latency", "idle", "silence")))
                ).scalar_one()
                == 0
            )
        events = client.get(f"/sessions/{session_id}/events", headers=headers).json()
        assert [e["kind"] for e in events] == ["check_in", "work"]

    def test_still_thinking_keeps_space_and_creates_nothing(
        self, client: TestClient, database: Database, clock: dict
    ) -> None:
        learner_id, headers = bootstrap(client)
        client.put("/me/wait-preference", json={"wait_seconds": 30}, headers=headers)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        before = table_counts(database, learner_id)
        clock["now"] = utc_now() + timedelta(seconds=40)
        assert (
            client.get(f"/sessions/{session_id}/wait", headers=headers).json()[
                "quiet_hint_available"
            ]
            is True
        )
        pressed = client.post(f"/sessions/{session_id}/still-thinking", headers=headers)
        assert pressed.status_code == 200, pressed.text
        state = pressed.json()
        assert state["still_thinking_count"] == 1
        assert state["quiet_hint_available"] is False, "the quiet period restarts"
        assert state["proactive_prompt"] == "none"
        clock["now"] = clock["now"] + timedelta(seconds=31)
        again = client.get(f"/sessions/{session_id}/wait", headers=headers).json()
        assert again["quiet_hint_available"] is True
        repeated = client.post(f"/sessions/{session_id}/still-thinking", headers=headers).json()
        assert repeated["still_thinking_count"] == 2
        assert table_counts(database, learner_id) == before
        with database.transaction() as db:
            assert db.get(SessionRow, session_id).revision == 1

    def test_help_returns_a_hint_immediately_even_inside_the_wait(
        self, client: TestClient, database: Database, clock: dict
    ) -> None:
        learner_id, headers = bootstrap(client)
        client.put("/me/wait-preference", json={"wait_seconds": 300}, headers=headers)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        client.post(f"/sessions/{session_id}/still-thinking", headers=headers)
        state = client.get(f"/sessions/{session_id}/wait", headers=headers).json()
        assert state["quiet_hint_available"] is False
        response = help_turn(client, headers, session_id, 1)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "committed"
        assert result["hint_id"] and result["utterance"]
        assert mastery(database, learner_id, LINEAR) is None
        after = client.get(f"/sessions/{session_id}/wait", headers=headers).json()
        assert after["next_hint_level"] == 2

    def test_wait_routes_reject_ended_sessions(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        assert client.post(f"/sessions/{session_id}/end", headers=headers).status_code == 200
        assert client.get(f"/sessions/{session_id}/wait", headers=headers).status_code == 409
        assert (
            client.post(f"/sessions/{session_id}/still-thinking", headers=headers).status_code
            == 409
        )

    def test_turn_rows_are_unchanged_by_waiting_endpoints(
        self, client: TestClient, database: Database
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        with database.transaction() as db:
            turns = db.execute(select(func.count()).select_from(TutorTurnRow)).scalar_one()
        client.get(f"/sessions/{session_id}/wait", headers=headers)
        client.post(f"/sessions/{session_id}/still-thinking", headers=headers)
        with database.transaction() as db:
            assert db.execute(select(func.count()).select_from(TutorTurnRow)).scalar_one() == turns


class TestTwoLearnerAuthorization:
    def test_new_routes_require_credentials(self, client: TestClient) -> None:
        for method, path, body in (
            ("get", "/me/wait-preference", None),
            ("put", "/me/wait-preference", {"wait_seconds": 30}),
            ("get", "/sessions/any/wait", None),
            ("post", "/sessions/any/still-thinking", None),
            ("post", "/sessions/any/help", {"expected_revision": 0}),
        ):
            response = getattr(client, method)(path, **({"json": body} if body else {}))
            assert response.status_code == 401, (method, path)

    def test_preferences_are_per_learner(self, client: TestClient) -> None:
        _, headers_a = bootstrap(client, "Learner A")
        _, headers_b = bootstrap(client, "Learner B")
        client.put("/me/wait-preference", json={"wait_seconds": 200}, headers=headers_a)
        assert client.get("/me/wait-preference", headers=headers_b).json()["source"] == "default"
        assert client.get("/me/wait-preference", headers=headers_a).json()["wait_seconds"] == 200

    def test_another_learners_session_is_not_found_on_every_new_session_route(
        self, client: TestClient, database: Database
    ) -> None:
        learner_a, headers_a = bootstrap(client, "Learner A")
        _, headers_b = bootstrap(client, "Learner B")
        session_id = start_session(client, headers_a)
        check_in(client, headers_a, session_id)
        before = table_counts(database, learner_a)

        missing = {
            "wait": client.get("/sessions/does-not-exist/wait", headers=headers_b),
            "still": client.post("/sessions/does-not-exist/still-thinking", headers=headers_b),
            "help": help_turn(client, headers_b, "does-not-exist", 0),
        }
        foreign = {
            "wait": client.get(f"/sessions/{session_id}/wait", headers=headers_b),
            "still": client.post(f"/sessions/{session_id}/still-thinking", headers=headers_b),
            "help": help_turn(client, headers_b, session_id, 1),
        }
        for name, response in foreign.items():
            assert response.status_code == 404, name
            assert response.json() == missing[name].json(), name
        assert table_counts(database, learner_a) == before
        owned = client.get(f"/sessions/{session_id}/wait", headers=headers_a)
        assert owned.status_code == 200
        assert owned.json()["still_thinking_count"] == 0
