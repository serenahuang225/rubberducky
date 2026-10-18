"""End-to-end tutor turns over the real API: policy, validation, idempotency and scope.

The deterministic mock provider drives the same coordinator, validation and persistence
path any provider would. Provider test doubles that leak, override the verifier or propose
unsafe effects prove the coordinator rejects the whole turn without partial effects.
"""

import itertools
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.clock import utc_now
from app.config import Settings
from app.db.database import Database
from app.db.models import (
    AssessmentRow,
    BKTCountedOpportunityRow,
    HintRow,
    MasteryEstimateRow,
    MemoryEntryRow,
    ObservationRow,
    SceneObjectRow,
    SessionRow,
    StepRow,
    TutorTurnRow,
)
from app.db.seed import DEMO_LEARNER_ADA
from app.inference.providers import MockTutorProvider, ProviderLabel
from app.learner.pairing import LearnerScope, issue_pairing_code
from app.main import create_app
from app.schemas.tutor import CheckInRequest
from app.tutor import coordinator
from tests.conftest import bootstrap

LINEAR = "concept.linear_equations"
DISTRIBUTION = "concept.distribution"
DOUBLE_LABEL = ProviderLabel(name="test-double", is_mock=False, label="Test double provider")

_key_counter = itertools.count(1)


def key(prefix: str = "k") -> str:
    return f"{prefix}-{next(_key_counter):08d}"


def start_session(client: TestClient, headers: dict[str, str], goal: str = "practice") -> str:
    response = client.post("/sessions", json={"goal": goal}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def post_turn(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    path: str,
    body: dict,
    turn_key: str,
):
    return client.post(
        f"/sessions/{session_id}/{path}",
        json=body,
        headers={**headers, "Idempotency-Key": turn_key},
    )


def check_in(
    client: TestClient, headers: dict[str, str], session_id: str, revision: int = 0, **overrides
) -> dict:
    body = {"expected_revision": revision, **overrides}
    response = post_turn(client, headers, session_id, "check-in", body, key("ci"))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "committed"
    return result


def work(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    text: str,
    revision: int,
    mode: str = "typed",
) -> dict:
    body = {"expected_revision": revision, "text": text, "input_mode": mode}
    response = post_turn(client, headers, session_id, "work", body, key("w"))
    assert response.status_code == 200, response.text
    return response.json()


def table_counts(database: Database, learner_id: str) -> dict[str, int]:
    with database.transaction() as db:
        return {
            name: db.execute(
                select(func.count())
                .select_from(model)
                .where(model.learner_id == learner_id)
            ).scalar_one()
            for name, model in (
                ("steps", StepRow),
                ("observations", ObservationRow),
                ("hints", HintRow),
                ("assessments", AssessmentRow),
                ("scene_objects", SceneObjectRow),
                ("memory", MemoryEntryRow),
                ("turns", TutorTurnRow),
            )
        }


def mastery(database: Database, learner_id: str, concept_id: str) -> float | None:
    with database.transaction() as db:
        row = db.execute(
            select(MasteryEstimateRow).where(
                MasteryEstimateRow.learner_id == learner_id,
                MasteryEstimateRow.concept_id == concept_id,
            )
        ).scalar_one_or_none()
    return None if row is None else row.p_known


def pair_seeded(database: Database, client: TestClient, learner_id: str) -> dict[str, str]:
    with database.transaction() as db:
        code = issue_pairing_code(db, learner_id, utc_now(), timedelta(minutes=5))
    response = client.post("/pairing/redeem", json={"code": code})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestPersona:
    def test_options_offer_three_appearances_and_five_ducks(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        response = client.get("/persona/options", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["appearances"] == ["animal", "older_adult", "younger_adult"]
        assert body["personalities"] == ["vincent", "zeeshan", "tony", "janelle", "mary"]
        assert body["comfort_overrides"] == ["none", "neutral_supportive", "reduced_sass"]

    @pytest.mark.parametrize("appearance", ["animal", "older_adult", "younger_adult"])
    @pytest.mark.parametrize(
        "personality", ["vincent", "zeeshan", "tony", "janelle", "mary"]
    )
    def test_first_run_appearance_and_personality_are_independently_selectable(
        self, client: TestClient, appearance: str, personality: str
    ) -> None:
        _, headers = bootstrap(client)
        response = client.put(
            "/me/tutor-configuration",
            json={"appearance": appearance, "personality": personality},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        me = client.get("/me", headers=headers).json()
        config = me["tutor_configuration"]
        assert config["appearance"] == appearance
        assert config["personality"] == personality
        assert config["comfort_override"] == "none"

    @pytest.mark.parametrize("appearance", ["animal", "older_adult", "younger_adult"])
    def test_appearance_never_changes_wording(self, client: TestClient, appearance: str) -> None:
        _, headers = bootstrap(client)
        client.put(
            "/me/tutor-configuration",
            json={"appearance": appearance, "personality": "tony"},
            headers=headers,
        )
        session_id = start_session(client, headers)
        result = check_in(client, headers, session_id)
        assert result["utterance"] == (
            "Tell me what you're thinking. Here's the problem: 2(x + 3) = 14. What's your first step?"
        )

    def test_comfort_override_applies_immediately(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        client.put(
            "/me/tutor-configuration",
            json={"appearance": "animal", "personality": "tony"},
            headers=headers,
        )
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        first = work(client, headers, session_id, "x + 3 = 7", 1)
        assert first["utterance"].startswith("That line of thought landed.")
        client.put(
            "/me/tutor-configuration",
            json={
                "appearance": "animal",
                "personality": "tony",
                "comfort_override": "neutral_supportive",
            },
            headers=headers,
        )
        second = work(client, headers, session_id, "2x + 6 = 14", 2)
        assert second["utterance"].startswith("Nice work.")


class TestCheckIn:
    def test_check_in_poses_the_problem_without_disclosing_anything(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        result = check_in(client, headers, session_id)
        assert result["action_type"] == "check_in_and_pose"
        assert result["provider"]["is_mock"] is True
        assert "mock" in result["provider"]["label"].lower()
        assert "2(x + 3) = 14" in result["utterance"]
        assert "2x + 6" not in result["utterance"]
        assert "x = 4" not in result["utterance"]
        assert result["answer_revealed"] is False
        assert result["current_problem"]["statement"] == "2(x + 3) = 14"
        state = client.get(f"/sessions/{session_id}/state", headers=headers).json()
        assert state["current_problem"]["statement"] == "2(x + 3) = 14"
        assert state["session"]["revision"] == 1

    def test_check_in_is_a_self_report_and_never_math_evidence(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        before = table_counts(database, learner_id)
        result = check_in(client, headers, session_id, energy="tired")
        assert result["pace"] == "lighter"
        student = result["student_input"]
        assert student["classification"] == "check_in"
        assert student["step_id"] is None
        (note,) = student["eligibility"]
        assert note["eligible"] is False and note["update_status"] == "ineligible"
        assert result["memory"]["status"] == "applied"
        after = table_counts(database, learner_id)
        # One self-report observation and one session-context entry; no work, no hint.
        assert after["observations"] == before["observations"] + 1
        assert after["memory"] == before["memory"] + 1
        assert after["steps"] == before["steps"]
        with database.transaction() as db:
            observation = db.get(ObservationRow, student["observation_ids"][0])
            assert observation is not None
            assert observation.evidence_kind == "self_report"
            assert observation.correct is None
            assert observation.concept_id is None
            entry = db.get(MemoryEntryRow, result["memory"]["applied_ids"][0])
            assert entry is not None
            assert entry.layer == "session_context"
            assert entry.session_id == session_id
            assert entry.evidence_kind == "self_report"
        assert mastery(database, learner_id, LINEAR) is None

    def test_goal_can_pose_the_explanation_exercise_first(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        result = check_in(client, headers, session_id, goal="explain_distribution")
        assert result["current_problem"]["kind"] == "explanation"


class TestWorkFeedback:
    def test_partial_distribution_gets_a_grounded_diagnostic_hint_not_the_answer(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, "2x + 3 = 14", 1)
        assert result["status"] == "committed"
        assert result["action_type"] == "diagnostic_hint"
        # Partial and grounded: asks about both terms, shows neither the step nor the answer.
        assert "every term" in result["utterance"]
        assert "2x + 6" not in result["utterance"]
        assert "x = 4" not in result["utterance"]
        assert result["answer_revealed"] is False
        assert result["hint_level"] == 1
        student = result["student_input"]
        assert student["classification"] == "partial_distribution"
        assert student["verification"]["status"] == "invalid"
        assert student["verification"]["reason"] == "not_equivalent"
        (note,) = student["eligibility"]
        assert note["eligible"] is False
        assert note["reason"] == "not_verified_assessment"
        hypothesis = result["hypothesis"]
        assert hypothesis["label"] == "Partial distribution"
        assert hypothesis["status"] == "tentative"
        assert hypothesis["confidence"] == 0.5
        assert hypothesis["alternatives"]
        assert hypothesis["evidence_kind"] == "inference"
        assert student["step_id"] in hypothesis["source_ids"]
        assert hypothesis["id"] in result["evidence_ids"]
        assert student["step_id"] in result["evidence_ids"]
        # The grouping mark is a tutor-authored scene object, never student evidence.
        assert [d["tool"] for d in result["drawings"]] == ["highlight", "draw_shape"]
        with database.transaction() as db:
            hint = db.get(HintRow, result["hint_id"])
            assert hint is not None
            assert hint.level == 1 and hint.answer_revealed is False
            marks = {
                row.id: row
                for row in db.execute(
                    select(SceneObjectRow).where(SceneObjectRow.learner_id == learner_id)
                ).scalars()
            }
            for drawing in result["drawings"]:
                row = marks[drawing["object_id"]]
                assert row.author_role == "tutor"
                assert row.teaching_step_id == result["turn_id"]
            observation = db.get(ObservationRow, student["observation_ids"][0])
            assert observation is not None
            assert observation.evidence_kind == "observed_work"
            assert observation.correct is False
        counts = table_counts(database, learner_id)
        # Statement plus two grouping marks; exactly one observation (the step's).
        assert counts["scene_objects"] == 3
        assert counts["observations"] == 2  # check-in self-report + step observation

    def test_repeated_partial_distribution_escalates_one_hint_level(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        first = work(client, headers, session_id, "2x + 3 = 14", 1)
        second = work(client, headers, session_id, "2x + 3 = 14", 2)
        assert first["hint_level"] == 1
        assert second["hint_level"] == 2
        assert "groups of" in second["utterance"]

    def test_valid_step_is_acknowledged_without_a_hint(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, "2x + 6 = 14", 1)
        assert result["action_type"] == "step_feedback"
        assert result["hint_id"] is None
        assert result["drawings"] == []
        assert result["student_input"]["classification"] == "valid_step"
        assert result["student_input"]["verification"]["status"] == "valid"

    def test_invalid_step_is_marked_not_equivalent_without_blame(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, "2x + 3 = 15", 1)
        assert result["action_type"] == "step_not_equivalent"
        assert result["student_input"]["verification"]["status"] == "invalid"
        assert result["hypothesis"] is None

    def test_uncheckable_input_is_unknown_not_incorrect(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, "__import__('os')", 1)
        assert result["action_type"] == "ask_rephrase"
        student = result["student_input"]
        assert student["classification"] == "unsupported"
        assert student["verification"]["status"] == "unknown"
        (note,) = student["eligibility"]
        assert note["eligible"] is False

    def test_unconfirmed_ink_is_never_stored_or_assessed(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        before = table_counts(database, learner_id)
        result = work(client, headers, session_id, "2x + 6 = 14", 1, mode="unconfirmed_ink")
        assert result["action_type"] == "confirm_ink"
        student = result["student_input"]
        assert student["classification"] == "unconfirmed_ink"
        assert student["step_id"] is None
        assert student["observation_ids"] == []
        after = table_counts(database, learner_id)
        assert after["steps"] == before["steps"]
        assert after["observations"] == before["observations"]
        # Explicit confirmation creates a separate step that is then assessed.
        confirmed = work(client, headers, session_id, "2x + 6 = 14", 2, mode="confirmed_ink")
        assert confirmed["action_type"] == "step_feedback"
        assert confirmed["student_input"]["step_id"] is not None
        with database.transaction() as db:
            step = db.get(StepRow, confirmed["student_input"]["step_id"])
            assert step is not None and step.input_mode == "confirmed_ink"


class TestEligibilityAndBKT:
    def test_two_independent_solutions_give_ten_nineteenths_then_point_eight_two(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        work(client, headers, session_id, "2x + 6 = 14", 1)
        solved = work(client, headers, session_id, "x = 4", 2)
        student = solved["student_input"]
        assert student["classification"] == "solution_with_reasoning"
        assert student["assessment_kind"] == "practice_check"
        assert student["assessment_independent"] is True
        (note,) = [e for e in student["eligibility"]]
        assert note["eligible"] is True and note["update_status"] == "counted"
        assert mastery(database, learner_id, LINEAR) == pytest.approx(10 / 19, abs=1e-12)

        assert solved["current_problem"]["statement"] == "3(x - 2) = 12"
        work(client, headers, session_id, "3x - 6 = 12", 3)
        transferred = work(client, headers, session_id, "x = 6", 4)
        assert transferred["student_input"]["assessment_kind"] == "transfer_check"
        assert transferred["student_input"]["assessment_independent"] is True
        assert mastery(database, learner_id, LINEAR) == pytest.approx(0.82, abs=1e-12)
        with database.transaction() as db:
            counted = list(
                db.execute(
                    select(BKTCountedOpportunityRow)
                    .where(BKTCountedOpportunityRow.learner_id == learner_id)
                    .order_by(BKTCountedOpportunityRow.sequence)
                ).scalars()
            )
        assert [row.sequence for row in counted] == [1, 2]
        assert counted[0].opportunity_key != counted[1].opportunity_key
        assert all(row.observed_correct for row in counted)
        readiness = client.get("/tracing/readiness", headers=headers).json()
        linear = next(c for c in readiness["concepts"] if c["concept_id"] == LINEAR)
        assert linear["counted_independent_opportunities"] == 2

    def test_hinted_success_remains_assisted_and_never_enters_independent_bkt(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        hinted = work(client, headers, session_id, "2x + 3 = 14", 1)
        assert hinted["action_type"] == "diagnostic_hint"
        work(client, headers, session_id, "2x + 6 = 14", 2)
        solved = work(client, headers, session_id, "x = 4", 3)
        student = solved["student_input"]
        assert student["classification"] == "solution_with_reasoning"
        assert student["assessment_independent"] is False
        (note,) = student["eligibility"]
        assert note["eligible"] is False
        assert note["reason"] == "assisted"
        assert note["update_status"] == "ineligible"
        assert mastery(database, learner_id, LINEAR) is None
        with database.transaction() as db:
            counted = db.execute(
                select(func.count())
                .select_from(BKTCountedOpportunityRow)
                .where(BKTCountedOpportunityRow.learner_id == learner_id)
            ).scalar_one()
            assert counted == 0
            note_row = db.get(MemoryEntryRow, solved["memory"]["applied_ids"][0])
            assert note_row is not None
            assert note_row.layer == "episodic_note"
            assert note_row.evidence_kind == "inference"
        readiness = client.get("/tracing/readiness", headers=headers).json()
        linear = next(c for c in readiness["concepts"] if c["concept_id"] == LINEAR)
        assert linear["counted_independent_opportunities"] == 0

    def test_correct_value_without_reasoning_is_not_independent_evidence(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, "x = 4", 1)
        student = result["student_input"]
        assert result["action_type"] == "reasoning_check"
        assert student["classification"] == "solution_without_reasoning"
        assert student["assessment_independent"] is False
        (note,) = student["eligibility"]
        assert note["eligible"] is False
        assert mastery(database, learner_id, LINEAR) is None

    def test_wrong_solution_is_an_independent_incorrect_opportunity(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        result = work(client, headers, session_id, "x = 5", 1)
        student = result["student_input"]
        assert result["action_type"] == "solution_feedback"
        assert student["classification"] == "wrong_solution"
        assert student["assessment_independent"] is True
        (note,) = student["eligibility"]
        assert note["eligible"] is True and note["update_status"] == "counted"
        # One independent incorrect response from the hand-set prior (VAL-BKT-001 fixture).
        assert mastery(database, learner_id, LINEAR) == pytest.approx(4 / 31, abs=1e-12)


class TestExplanation:
    def test_explanation_follow_up_then_adequate_feedback(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id, goal="explain_distribution")
        weak = work(client, headers, session_id, "2x", 1)
        assert weak["action_type"] == "explanation_follow_up"
        assert "each term" in weak["utterance"]
        assert weak["student_input"]["classification"] == "explanation"
        judgment = weak["student_input"]["explanation_judgment"]
        assert judgment["evidence_kind"] == "inference"
        assert judgment["judgment_scope"] == "pedagogical"
        (note,) = weak["student_input"]["eligibility"]
        assert note["eligible"] is False
        # An incomplete explanation keeps correctness unmeasured, so nothing is counted.
        assert note["reason"] == "no_response_correctness"

        adequate = work(
            client,
            headers,
            session_id,
            "2(x + 3) is two groups of (x + 3), so the 2 multiplies each term "
            "and the value stays equal.",
            2,
        )
        assert adequate["action_type"] == "explanation_feedback"
        met = {
            j["criterion_id"]
            for j in adequate["student_input"]["explanation_judgment"]["judgments"]
            if j["status"] == "met"
        }
        assert len(met) >= 2
        (adequate_note,) = adequate["student_input"]["eligibility"]
        assert adequate_note["eligible"] is False
        assert adequate_note["reason"] == "explanation_not_response_opportunity"


class TestIdempotencyAndRevisions:
    def test_retry_with_same_key_replays_without_duplicate_effects(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        body = {"expected_revision": 0, "energy": "ready"}
        retry_key = key("idem")
        first = post_turn(client, headers, session_id, "check-in", body, retry_key)
        # Retry with the identical key and content.
        second = post_turn(client, headers, session_id, "check-in", body, retry_key)
        assert first.status_code == 200 and second.status_code == 200
        first_result, second_result = first.json(), second.json()
        assert second_result["turn_id"] == first_result["turn_id"]
        assert second_result["replayed"] is True
        assert second_result["utterance"] == first_result["utterance"]
        counts = table_counts(database, learner_id)
        assert counts["turns"] == 1
        assert counts["observations"] == 1

    def test_same_key_with_different_content_conflicts(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        turn_key = key("conflict")
        first = post_turn(
            client, headers, session_id, "check-in", {"expected_revision": 0}, turn_key
        )
        assert first.status_code == 200
        conflict = post_turn(
            client,
            headers,
            session_id,
            "check-in",
            {"expected_revision": 0, "energy": "tired"},
            turn_key,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"

    def test_stale_expected_revision_conflicts(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        stale = post_turn(
            client,
            headers,
            session_id,
            "work",
            {"expected_revision": 0, "text": "2x + 6 = 14"},
            key("stale"),
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "revision_conflict"

    def test_missing_idempotency_key_is_rejected(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        response = client.post(
            f"/sessions/{session_id}/work",
            json={"expected_revision": 0, "text": "x"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_sequential_commands_at_the_same_revision_advance_once(
        self, client: TestClient, database: Database
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        first = post_turn(
            client, headers, session_id, "work",
            {"expected_revision": 1, "text": "x + 3 = 7"}, key("seq"),
        )
        second = post_turn(
            client, headers, session_id, "work",
            {"expected_revision": 1, "text": "2x + 6 = 14"}, key("seq"),
        )
        assert first.status_code == 200 and first.json()["status"] == "committed"
        assert second.status_code == 409
        with database.transaction() as db:
            row = db.get(SessionRow, session_id)
            assert row is not None and row.revision == 2

    def test_concurrent_commands_cannot_both_advance_the_revision(
        self, client: TestClient, database: Database
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def submit(name: str, text: str) -> None:
            barrier.wait(timeout=10)
            results[name] = post_turn(
                client, headers, session_id, "work",
                {"expected_revision": 1, "text": text}, key("race"),
            )

        threads = [
            threading.Thread(target=submit, args=("a", "x + 3 = 7")),
            threading.Thread(target=submit, args=("b", "2x + 6 = 14")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        outcomes = sorted(
            (response.status_code, str(response.json().get("status")))
            for response in results.values()  # type: ignore[union-attr]
        )
        assert outcomes[0] == (200, "committed")
        assert outcomes[1][0] in (409, 503)
        with database.transaction() as db:
            row = db.get(SessionRow, session_id)
            assert row is not None and row.revision == 2
            committed = db.execute(
                select(func.count())
                .select_from(TutorTurnRow)
                .where(TutorTurnRow.session_id == session_id, TutorTurnRow.status == "committed")
            ).scalar_one()
            assert committed == 2  # the check-in plus exactly one of the racing commands

    def test_turn_is_superseded_when_the_session_moves_during_inference(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        scope = LearnerScope(learner_id=learner_id, credential_id="test")
        provider = MockTutorProvider()
        body = CheckInRequest(expected_revision=0)
        reserved = coordinator._reserve(
            database, scope, session_id, "check_in", body, key("super"), provider.label(), utc_now()
        )
        assert isinstance(reserved, coordinator._Reserved)
        # The session advances (ends) while inference would be running.
        ended = client.post(f"/sessions/{session_id}/end", headers=headers)
        assert ended.status_code == 200
        result = coordinator._commit(
            database, scope, session_id, reserved, body, None, None, [], provider, utc_now()
        )
        assert result.status == "superseded"
        assert result.utterance is None
        assert result.rejections[0].code == "revision_changed"
        # The student's check-in evidence from the reserve stays durable regardless.
        assert result.student_input is not None
        assert result.student_input.classification == "check_in"
        stored = client.get(
            f"/sessions/{session_id}/turns/{result.turn_id}", headers=headers
        ).json()
        assert stored["status"] == "superseded"


class TestProviderMatrix:
    """The mock runs the real path; misbehaving doubles are rejected without effects."""

    def _double(self, mutate) -> object:
        mock = MockTutorProvider()

        class Double:
            def label(self) -> ProviderLabel:
                return DOUBLE_LABEL

            def draft(self, inputs):
                return mutate(mock.draft(inputs))

        return Double()

    def _run_with_double(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch, mutate
    ) -> tuple[str, dict, dict[str, int], dict[str, int]]:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        monkeypatch.setattr(
            "app.tutor.coordinator.get_provider", lambda settings: self._double(mutate)
        )
        before = table_counts(database, learner_id)
        response = post_turn(
            client, headers, session_id, "work",
            {"expected_revision": 1, "text": "2x + 3 = 14"}, key("double"),
        )
        assert response.status_code == 200, response.text
        after = table_counts(database, learner_id)
        return learner_id, response.json(), before, after

    def test_valid_mock_turn_commits_text_stroke_and_effects(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        before = table_counts(database, learner_id)
        result = work(client, headers, session_id, "2x + 3 = 14", 1)
        assert result["status"] == "committed"
        assert result["provider"]["is_mock"] is True
        assert result["utterance"] and result["drawings"] and result["hint_id"]
        after = table_counts(database, learner_id)
        assert after["hints"] == before["hints"] + 1
        assert after["scene_objects"] == before["scene_objects"] + 2
        # The draft grounded itself in this turn's evidence and the bounded context.
        assert result["evidence_ids"]
        assert result["context_source_ids"]

    def test_draft_revealing_the_answer_is_rejected_without_effects(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, result, before, after = self._run_with_double(
            client, database, monkeypatch,
            lambda draft: draft.model_copy(update={"utterance": "It becomes 2x + 6 = 14."}),
        )
        assert result["status"] == "rejected"
        assert {r["code"] for r in result["rejections"]} == {"forbidden_disclosure"}
        assert result["utterance"] is None
        # The student's own step stays recorded; no tutor text, mark, hint or memory lands.
        assert after["steps"] == before["steps"] + 1
        assert after["hints"] == before["hints"]
        assert after["scene_objects"] == before["scene_objects"]
        assert after["memory"] == before["memory"]

    def test_draft_overriding_the_verifier_is_rejected(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, result, _, _ = self._run_with_double(
            client, database, monkeypatch,
            # The verifier said the step is invalid; the provider claims it is valid.
            lambda draft: draft.model_copy(update={"step_assessment": "valid"}),
        )
        assert result["status"] == "rejected"
        assert {r["code"] for r in result["rejections"]} == {"provider_overrides_verifier"}
        assert result["student_input"]["verification"]["status"] == "invalid"

    def test_draft_with_unsafe_drawings_is_rejected(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def mutate(draft):
            return draft.model_copy(
                update={
                    "drawing_actions": [
                        *draft.drawing_actions,
                        {"tool": "execute_js", "code": "alert(1)"},
                    ]
                }
            )

        _, result, before, after = self._run_with_double(client, database, monkeypatch, mutate)
        assert result["status"] == "rejected"
        assert "invalid_tool" in {r["code"] for r in result["rejections"]}
        assert after["scene_objects"] == before["scene_objects"]
        assert after["hints"] == before["hints"]

    def test_draft_with_over_budget_memory_proposals_is_rejected(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def mutate(draft):
            proposal = {
                "schema_version": "memory-update-proposal.v1",
                "operation": "flag_note_for_review",
                "learner_id": "ignored",
                "memory_id": "note-1",
                "reason": "check",
                "source_ids": ["obs-1"],
            }
            return draft.model_copy(
                update={"proposed_memory_updates": [dict(proposal) for _ in range(6)]}
            )

        _, result, before, after = self._run_with_double(client, database, monkeypatch, mutate)
        assert result["status"] == "rejected"
        assert {r["code"] for r in result["rejections"]} == {"too_many_proposals"}
        assert after["memory"] == before["memory"]

    def test_draft_citing_invented_evidence_is_rejected(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, result, _, _ = self._run_with_double(
            client, database, monkeypatch,
            lambda draft: draft.model_copy(
                update={"evidence_ids": [*draft.evidence_ids, "observation.invented"]}
            ),
        )
        assert result["status"] == "rejected"
        assert "uncitable_evidence" in {r["code"] for r in result["rejections"]}

    def test_provider_failure_fails_the_turn_honestly(
        self, client: TestClient, database: Database, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Broken:
            def label(self) -> ProviderLabel:
                return DOUBLE_LABEL

            def draft(self, inputs):
                raise RuntimeError("simulated provider crash")

        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        monkeypatch.setattr(
            "app.tutor.coordinator.get_provider", lambda settings: Broken()
        )
        response = post_turn(
            client, headers, session_id, "work",
            {"expected_revision": 1, "text": "2x + 3 = 14"}, key("broken"),
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "failed"
        assert result["rejections"][0]["code"] == "provider_error"
        assert result["utterance"] is None
        stored = client.get(
            f"/sessions/{session_id}/turns/{result['turn_id']}", headers=headers
        ).json()
        assert stored["status"] == "failed"

    def test_unrelated_operations_proceed_while_inference_is_blocked(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        mock = MockTutorProvider()

        class Blocking:
            def label(self) -> ProviderLabel:
                return mock.label()

            def draft(self, inputs):
                entered.set()
                assert release.wait(timeout=15)
                return mock.draft(inputs)

        monkeypatch.setattr(
            "app.tutor.coordinator.get_provider", lambda settings: Blocking()
        )
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        outcome: dict[str, object] = {}

        def run() -> None:
            outcome["response"] = post_turn(
                client, headers, session_id, "check-in", {"expected_revision": 0}, key("block")
            )

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert entered.wait(timeout=15)
            # Inference holds no transaction: unrelated reads and writes keep working.
            assert client.get("/sessions", headers=headers).status_code == 200
            other = client.post("/sessions", json={"goal": "unrelated"}, headers=headers)
            assert other.status_code == 201
        finally:
            release.set()
            thread.join(timeout=15)
        assert outcome["response"].status_code == 200  # type: ignore[union-attr]
        assert outcome["response"].json()["status"] == "committed"  # type: ignore[union-attr]


class TestScopeAndState:
    def test_other_learner_cannot_read_or_write_turns_or_state(
        self, client: TestClient, database: Database
    ) -> None:
        _, headers_a = bootstrap(client, "Learner A")
        _, headers_b = bootstrap(client, "Learner B")
        session_id = start_session(client, headers_a)
        result = check_in(client, headers_a, session_id)
        for method, path in [
            ("GET", f"/sessions/{session_id}/state"),
            ("GET", f"/sessions/{session_id}/events"),
            ("GET", f"/sessions/{session_id}/turns/{result['turn_id']}"),
        ]:
            response = client.request(method, path, headers=headers_b)
            assert response.status_code == 404
        for path, body in [
            ("check-in", {"expected_revision": 1}),
            ("work", {"expected_revision": 1, "text": "2x + 6 = 14"}),
        ]:
            response = post_turn(client, headers_b, session_id, path, body, key("foreign"))
            assert response.status_code == 404
        # Same response as a session that does not exist at all: no existence oracle.
        missing = client.get("/sessions/does-not-exist/state", headers=headers_b)
        foreign = client.get(f"/sessions/{session_id}/state", headers=headers_b)
        assert missing.json() == foreign.json()
        with database.transaction() as db:
            row = db.get(SessionRow, session_id)
            assert row is not None and row.revision == 1

    def test_session_state_supports_resume(
        self, client: TestClient, database: Database
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id, energy="tired")
        work(client, headers, session_id, "2x + 3 = 14", 1)
        state = client.get(f"/sessions/{session_id}/state", headers=headers).json()
        assert state["session"]["revision"] == 2
        assert state["current_problem"]["statement"] == "2(x + 3) = 14"
        assert state["pace"] == "lighter"
        assert state["pending_turn_id"] is None
        assert state["session_context_recheck"] is False
        assert state["persona"] is None

        # A new session expires the old temporary context, so a recheck is signalled.
        second = start_session(client, headers)
        state2 = client.get(f"/sessions/{second}/state", headers=headers).json()
        assert state2["session_context_recheck"] is True
        assert state2["current_problem"] is None

    def test_turn_events_are_chronological(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        first = check_in(client, headers, session_id)
        second = work(client, headers, session_id, "2x + 3 = 14", 1)
        events = client.get(f"/sessions/{session_id}/events", headers=headers).json()
        assert [event["turn_id"] for event in events] == [first["turn_id"], second["turn_id"]]
        assert all(event["status"] == "committed" for event in events)

    def test_turns_require_an_active_session_and_a_posed_problem(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        response = post_turn(
            client, headers, session_id, "work",
            {"expected_revision": 0, "text": "x"}, key("early"),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "no_active_problem"
        ended = client.post(f"/sessions/{session_id}/end", headers=headers)
        assert ended.status_code == 200
        response = post_turn(
            client, headers, session_id, "check-in", {"expected_revision": 1}, key("closed")
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "session_not_active"

    def test_returning_session_surfaces_earlier_assistance(
        self, client: TestClient, database: Database
    ) -> None:
        # Seeded Ada has an episodic note about assisted grouping help (fictional seed).
        headers = pair_seeded(database, client, DEMO_LEARNER_ADA)
        session_id = start_session(client, headers)
        result = check_in(client, headers, session_id)
        assert "Last time, grouping both terms helped after a hint." in result["utterance"]
        # The reminder cites the actual note, which remains labeled as its own evidence.
        assert result["evidence_ids"]
        layers = client.get(
            "/memory/layers", headers=headers, params={"session_id": session_id}
        ).json()
        assert layers["episodic_notes"]


class TestReturningSessionAdaptation:
    """A returning session's instruction follows the learner's OWN submitted evidence.

    Unlike the seeded-Ada case (fictional illustrative history), this journey records
    real submitted work first, then restarts the process over the same file and compares
    the returning learner's next instruction with a matched cold start (VAL-MEM-003,
    VAL-CROSS-001, VAL-TEACH-011).
    """

    def test_returning_instruction_uses_submitted_evidence_after_restart(
        self, seeded_db_url: str
    ) -> None:
        def make_client() -> TestClient:
            return TestClient(create_app(Settings(database_url=seeded_db_url)))

        with make_client() as client:
            _, headers = bootstrap(client, "Returning learner")
            first = start_session(client, headers)
            cold_like_first = check_in(client, headers, first)
            assert "Last time" not in cold_like_first["utterance"]
            hinted = work(client, headers, first, "2x + 3 = 14", 1)
            assert hinted["action_type"] == "diagnostic_hint"
            assert hinted["hint_id"] is not None
            work(client, headers, first, "2x + 6 = 14", 2)
            solved = work(client, headers, first, "x = 4", 3)
            # Assisted success: truthful praise, never independent mastery.
            assert solved["student_input"]["assessment_independent"] is False
            (note_id,) = solved["memory"]["applied_ids"]
            layers = client.get(
                "/memory/layers", headers=headers, params={"session_id": first}
            ).json()
            (note,) = [n for n in layers["episodic_notes"] if n["entry"]["id"] == note_id]
            # The saved note is grounded in the actual hint and step evidence.
            assert hinted["hint_id"] in note["entry"]["source_ids"]
            assert note["entry"]["provenance"] == "submitted"
            ended = client.post(f"/sessions/{first}/end", headers=headers)
            assert ended.status_code == 200
            assert ended.json()["status"] == "ended"

        # A simulated process restart over the same file: the same bearer credential and
        # the saved evidence still drive the next session's instruction.
        with make_client() as restarted:
            second = start_session(restarted, headers)
            assert second != first
            returning = check_in(restarted, headers, second)
            assert (
                "Last time, grouping both terms helped after a hint."
                in returning["utterance"]
            )
            # The concise justification cites the actual stored note as its source.
            assert note_id in returning["evidence_ids"]
            assert returning["decision_justification"] == (
                "Returning: earlier grouping help was assisted, so pose the same problem with a "
                "reminder drawn from that note and leave the work to the learner."
            )
            assert returning["current_problem"]["statement"] == "2(x + 3) = 14"

            # A matched cold start on the same restarted server lacks that branch.
            _, cold_headers = bootstrap(restarted, "Cold learner")
            cold_session = start_session(restarted, cold_headers)
            cold = check_in(restarted, cold_headers, cold_session)
            assert "Last time" not in cold["utterance"]
            assert note_id not in cold["evidence_ids"]
            assert cold["decision_justification"] == (
                "New session: pose the unit's first problem and leave the work to the learner."
            )
