"""Races, interruption and restart recovery over the real API with a file-backed SQLite DB.

A gated provider double blocks inside inference so each scenario controls exactly when the
late response arrives. The assertions compare durable counts before and after, because the
contract is about effects: a stale reply may add no text, hint, mark, evidence or memory.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.clock import utc_now
from app.config import Settings
from app.db.database import Database
from app.db.models import (
    SceneObjectRow,
    SceneOperationRow,
    SessionRow,
    StepRow,
    TutorTurnRow,
)
from app.inference.providers import MockTutorProvider, ProviderLabel
from app.learner.pairing import LearnerScope
from app.main import create_app
from app.schemas.tutor import WorkRequest
from app.tutor import coordinator
from tests.conftest import bootstrap
from tests.test_tutor_turns import (
    DOUBLE_LABEL,
    check_in,
    key,
    post_turn,
    start_session,
    table_counts,
    work,
)

Headers = dict[str, str]


class GatedProvider:
    """Mock drafts, but the first ``gated_calls`` calls wait for ``release`` inside inference."""

    def __init__(self, gated_calls: int = 1) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._gated_calls = gated_calls
        self._lock = threading.Lock()
        self._mock = MockTutorProvider()

    def label(self) -> ProviderLabel:
        return DOUBLE_LABEL

    def draft(self, inputs: Any) -> Any:
        with self._lock:
            self.calls += 1
            gated = self.calls <= self._gated_calls
        if gated:
            self.entered.set()
            assert self.release.wait(timeout=20), "test never released the gated provider"
        return self._mock.draft(inputs)


@contextmanager
def background(call: Callable[[], Any]) -> Iterator[dict[str, Any]]:
    """Run ``call`` on a thread; the dict gets ``response`` once it finishes."""
    outcome: dict[str, Any] = {}

    def run() -> None:
        outcome["response"] = call()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        yield outcome
    finally:
        thread.join(timeout=30)
        assert not thread.is_alive()


def gate(monkeypatch: pytest.MonkeyPatch, provider: GatedProvider) -> None:
    monkeypatch.setattr("app.tutor.coordinator.get_provider", lambda settings: provider)


def state(client: TestClient, headers: Headers, session_id: str) -> dict:
    response = client.get(f"/sessions/{session_id}/state", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def scene(client: TestClient, headers: Headers, session_id: str) -> dict:
    response = client.get(f"/sessions/{session_id}/scene", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def stroke(client: TestClient, headers: Headers, session_id: str, x: float = 300.0) -> dict:
    revision = scene(client, headers, session_id)["scene_revision"]
    response = client.post(
        f"/sessions/{session_id}/scene/operations",
        json={
            "operation_id": key("op"),
            "expected_scene_revision": revision,
            "action": {
                "op": "add_stroke",
                "points": [{"x": x, "y": 400.0}, {"x": x + 40.0, "y": 430.0}],
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def work_body(text: str, revision: int) -> dict:
    return {"expected_revision": revision, "text": text, "input_mode": "typed"}


def effect_counts(database: Database, learner_id: str) -> dict[str, int]:
    return table_counts(database, learner_id)


def tutor_visible(client: TestClient, headers: Headers, session_id: str) -> list[dict]:
    return [o for o in scene(client, headers, session_id)["objects"] if o["author_role"] == "tutor"]


@pytest.fixture
def gated_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, Headers, str, GatedProvider]:
    learner_id, headers = bootstrap(client)
    session_id = start_session(client, headers)
    check_in(client, headers, session_id)
    provider = GatedProvider()
    gate(monkeypatch, provider)
    return learner_id, headers, session_id, provider


class TestDuplicatesAndConcurrency:
    def test_pending_identical_retry_finishes_once_and_late_original_replays_it(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        learner_id, headers, session_id, provider = gated_session
        before = effect_counts(database, learner_id)
        turn_key = key("dup")
        body = work_body("2x + 3 = 14", 1)
        with background(
            lambda: post_turn(client, headers, session_id, "work", body, turn_key)
        ) as original:
            assert provider.entered.wait(timeout=10)
            # The first request is still inferring; the identical retry finishes the turn.
            retry = post_turn(client, headers, session_id, "work", body, turn_key)
            assert retry.status_code == 200 and retry.json()["status"] == "committed"
            provider.release.set()
        late = original["response"]
        assert late.status_code == 200
        assert late.json()["turn_id"] == retry.json()["turn_id"]
        assert late.json()["status"] == "committed" and late.json()["replayed"] is True
        after = effect_counts(database, learner_id)
        assert after["turns"] == before["turns"] + 1
        assert after["steps"] == before["steps"] + 1
        assert after["observations"] == before["observations"] + 1
        assert after["hints"] == before["hints"] + 1
        assert after["scene_objects"] == before["scene_objects"] + 2

    def test_completed_retry_after_a_lost_acknowledgment_adds_no_effects(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        turn_key = key("lost")
        body = work_body("2x + 3 = 14", 1)
        first = post_turn(client, headers, session_id, "work", body, turn_key).json()
        settled = effect_counts(database, learner_id)
        revision = state(client, headers, session_id)["session"]["revision"]
        for _ in range(3):
            retry = post_turn(client, headers, session_id, "work", body, turn_key).json()
            assert retry["turn_id"] == first["turn_id"] and retry["replayed"] is True
            assert retry["utterance"] == first["utterance"]
            assert retry["drawings"] == first["drawings"]
        assert effect_counts(database, learner_id) == settled
        assert state(client, headers, session_id)["session"]["revision"] == revision

    def test_simultaneous_identical_commands_share_one_turn(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        before = effect_counts(database, learner_id)
        barrier = threading.Barrier(2)
        responses: list[Any] = []
        turn_key = key("same")
        body = work_body("2x + 3 = 14", 1)

        def submit() -> None:
            barrier.wait(timeout=10)
            responses.append(post_turn(client, headers, session_id, "work", body, turn_key))

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert [r.status_code for r in responses] == [200, 200]
        assert len({r.json()["turn_id"] for r in responses}) == 1
        after = effect_counts(database, learner_id)
        assert after["turns"] == before["turns"] + 1
        assert after["hints"] == before["hints"] + 1
        assert after["steps"] == before["steps"] + 1

    def test_unrelated_database_work_proceeds_while_inference_is_blocked(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        learner_id, headers, session_id, provider = gated_session
        other_id, other_headers = bootstrap(client, "Another learner")
        other_session = start_session(client, other_headers)
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("slow")
            )
        ) as slow:
            assert provider.entered.wait(timeout=10)
            # While the first learner's provider call is blocked, writes elsewhere succeed.
            assert state(client, headers, session_id)["pending_turn_id"] is not None
            committed_stroke = stroke(client, headers, session_id)
            assert committed_stroke["kind"] == "add_object"
            ended = client.post(f"/sessions/{other_session}/end", headers=other_headers)
            assert ended.status_code == 200
            other_pref = client.put(
                "/me/tutor-configuration",
                json={"appearance": "animal", "personality": "gentle"},
                headers=other_headers,
            )
            assert other_pref.status_code == 200, other_pref.text
            with database.transaction() as db:
                assert db.execute(select(func.count()).select_from(SessionRow)).scalar_one() >= 2
            provider.release.set()
        result = slow["response"].json()
        # A student stroke during inference is more work on the board, not a cancellation.
        assert result["status"] == "committed"
        assert result["drawings"]
        assert other_id != learner_id

    def test_response_effects_commit_atomically_or_not_at_all(
        self,
        client: TestClient,
        database: Database,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        mock = MockTutorProvider()

        class Unsafe:
            def label(self) -> ProviderLabel:
                return DOUBLE_LABEL

            def draft(self, inputs: Any) -> Any:
                draft = mock.draft(inputs)
                # Valid text and drawings, plus one memory proposal the validator rejects.
                return draft.model_copy(
                    update={
                        "proposed_memory_updates": [
                            {"kind": "create_episodic_note", "content": "bad", "source_ids": ["x"]}
                        ]
                    }
                )

        monkeypatch.setattr("app.tutor.coordinator.get_provider", lambda settings: Unsafe())
        before = effect_counts(database, learner_id)
        result = post_turn(
            client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("atomic")
        ).json()
        after = effect_counts(database, learner_id)
        assert result["status"] == "rejected"
        assert result["utterance"] is None and result["drawings"] == []
        assert after["hints"] == before["hints"]
        assert after["scene_objects"] == before["scene_objects"]
        assert after["memory"] == before["memory"]
        assert after["steps"] == before["steps"] + 1


class TestInterruptionAndStaleOutput:
    def test_explicit_interrupt_drops_the_late_reply_and_a_following_turn_succeeds(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        learner_id, headers, session_id, provider = gated_session
        assert state(client, headers, session_id)["session"]["cancellation_epoch"] == 0
        before = effect_counts(database, learner_id)
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("intr")
            )
        ) as slow:
            assert provider.entered.wait(timeout=10)
            pending = state(client, headers, session_id)["pending_turn_id"]
            interrupted = client.post(
                f"/sessions/{session_id}/interrupt",
                json={"observed_epoch": 0, "reason": "speech_barge_in"},
                headers=headers,
            )
            assert interrupted.status_code == 200, interrupted.text
            body = interrupted.json()
            assert body["interrupted_turn_ids"] == [pending]
            assert body["cancellation_epoch"] == 1 and body["replayed"] is False
            # The learner no longer sees "thinking" even though the provider is still blocked.
            assert state(client, headers, session_id)["pending_turn_id"] is None
            provider.release.set()
        late = slow["response"].json()
        assert late["status"] == "superseded"
        assert [r["code"] for r in late["rejections"]] == ["interrupted"]
        assert late["utterance"] is None and late["drawings"] == [] and late["hint_id"] is None
        after = effect_counts(database, learner_id)
        assert after["hints"] == before["hints"]
        assert after["scene_objects"] == before["scene_objects"]
        assert after["memory"] == before["memory"]
        # Recorded student work is not undone by interrupting the tutor's reply.
        assert after["steps"] == before["steps"] + 1
        current = state(client, headers, session_id)
        follow = post_turn(
            client,
            headers,
            session_id,
            "work",
            work_body("2x + 6 = 14", current["session"]["revision"]),
            key("after"),
        ).json()
        assert follow["status"] == "committed" and follow["utterance"]
        assert follow["cancellation_epoch"] == 1

    def test_interrupt_retry_is_replayed_and_does_not_cancel_a_newer_turn(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        first = client.post(
            f"/sessions/{session_id}/interrupt", json={"observed_epoch": 0}, headers=headers
        ).json()
        assert first["cancellation_epoch"] == 1 and first["replayed"] is False
        provider = GatedProvider()
        gate(monkeypatch, provider)
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("new")
            )
        ) as newer:
            assert provider.entered.wait(timeout=10)
            # A lost acknowledgment makes the client retry the same interrupt.
            retry = client.post(
                f"/sessions/{session_id}/interrupt", json={"observed_epoch": 0}, headers=headers
            ).json()
            assert retry["replayed"] is True and retry["cancellation_epoch"] == 1
            assert retry["interrupted_turn_ids"] == []
            provider.release.set()
        assert newer["response"].json()["status"] == "committed"
        impossible = client.post(
            f"/sessions/{session_id}/interrupt", json={"observed_epoch": 7}, headers=headers
        )
        assert impossible.status_code == 409
        assert impossible.json()["error"]["code"] == "epoch_conflict"

    def test_concurrent_interrupts_advance_the_epoch_once(
        self, client: TestClient, gated_session: tuple[str, Headers, str, GatedProvider]
    ) -> None:
        _, headers, session_id, _ = gated_session
        barrier = threading.Barrier(2)
        results: list[dict] = []

        def interrupt() -> None:
            barrier.wait(timeout=10)
            response = client.post(
                f"/sessions/{session_id}/interrupt", json={"observed_epoch": 0}, headers=headers
            )
            assert response.status_code == 200, response.text
            results.append(response.json())

        threads = [threading.Thread(target=interrupt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert sorted(r["replayed"] for r in results) == [False, True]
        assert {r["cancellation_epoch"] for r in results} == {1}

    def test_newer_work_withdraws_the_pending_reply_immediately(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        learner_id, headers, session_id, provider = gated_session
        before = effect_counts(database, learner_id)
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("old")
            )
        ) as old:
            assert provider.entered.wait(timeout=10)
            # The old turn is reserved at revision 2 and still blocked in inference.
            newer = post_turn(
                client, headers, session_id, "work", work_body("2x + 6 = 14", 2), key("fresh")
            )
            assert newer.status_code == 200 and newer.json()["status"] == "committed"
            provider.release.set()
        stale = old["response"].json()
        assert stale["status"] == "superseded"
        assert stale["rejections"][-1]["code"] == "superseded_by_work"
        assert stale["drawings"] == [] and stale["utterance"] is None
        assert state(client, headers, session_id)["session"]["cancellation_epoch"] == 1
        after = effect_counts(database, learner_id)
        assert after["steps"] == before["steps"] + 2  # both student steps are recorded
        # Nothing from the stale reply landed: the only hint is the current turn's, if any.
        assert stale["hint_id"] is None
        assert after["hints"] == before["hints"] + (1 if newer.json()["hint_id"] else 0)
        stored = client.get(
            f"/sessions/{session_id}/turns/{stale['turn_id']}", headers=headers
        ).json()
        assert stored["status"] == "superseded"

    def test_new_problem_drops_a_late_reply_and_never_overprints_statements(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        _learner_id, headers, session_id, provider = gated_session
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 6 = 14", 1), key("late")
            )
        ) as late:
            assert provider.entered.wait(timeout=10)
            solved = post_turn(
                client, headers, session_id, "work", work_body("x = 4", 2), key("solve")
            ).json()
            assert solved["status"] == "committed"
            assert solved["current_problem"]["statement"] == "3(x - 2) = 12"
            provider.release.set()
        assert late["response"].json()["status"] == "superseded"
        visible = tutor_visible(client, headers, session_id)
        statements = [o for o in visible if o["semantic_role"] == "problem_statement"]
        assert [o["payload"]["text"] for o in statements] == ["3(x - 2) = 12"]
        assert state(client, headers, session_id)["session"]["cancellation_epoch"] >= 1

    def test_source_deletion_during_inference_drops_the_late_reply(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        learner_id, headers, session_id, provider = gated_session
        before = effect_counts(database, learner_id)
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("src")
            )
        ) as slow:
            assert provider.entered.wait(timeout=10)
            pending_id = state(client, headers, session_id)["pending_turn_id"]
            pending = client.get(
                f"/sessions/{session_id}/turns/{pending_id}", headers=headers
            ).json()
            observation_id = pending["student_input"]["observation_ids"][0]
            deleted = client.delete(f"/memory/evidence/{observation_id}", headers=headers)
            assert deleted.status_code == 200, deleted.text
            provider.release.set()
        late = slow["response"].json()
        assert late["status"] == "superseded"
        assert late["utterance"] is None and late["drawings"] == []
        assert state(client, headers, session_id)["session"]["cancellation_epoch"] == 1
        after = effect_counts(database, learner_id)
        assert after["hints"] == before["hints"]
        assert after["scene_objects"] == before["scene_objects"]
        # A fresh current turn still works after the source change.
        revision = state(client, headers, session_id)["session"]["revision"]
        fresh = post_turn(
            client, headers, session_id, "work", work_body("2x + 6 = 14", revision), key("ok")
        ).json()
        assert fresh["status"] == "committed"

    def test_session_deletion_during_inference_commits_nothing(
        self,
        client: TestClient,
        database: Database,
        gated_session: tuple[str, Headers, str, GatedProvider],
    ) -> None:
        _learner_id, headers, session_id, provider = gated_session
        with background(
            lambda: post_turn(
                client, headers, session_id, "work", work_body("2x + 3 = 14", 1), key("gone")
            )
        ) as slow:
            assert provider.entered.wait(timeout=10)
            deleted = client.delete(f"/sessions/{session_id}", headers=headers)
            assert deleted.status_code == 200, deleted.text
            provider.release.set()
        assert slow["response"].status_code == 409
        assert slow["response"].json()["error"]["code"] == "turn_removed"
        with database.transaction() as db:
            assert db.get(SessionRow, session_id) is None
            assert (
                db.execute(
                    select(func.count())
                    .select_from(SceneObjectRow)
                    .where(SceneObjectRow.session_id == session_id)
                ).scalar_one()
                == 0
            )


class TestRestartRecovery:
    def _reserve_without_finishing(
        self, database: Database, learner_id: str, session_id: str, text: str, revision: int
    ) -> tuple[str, WorkRequest]:
        body = WorkRequest(expected_revision=revision, text=text)
        turn_key = key("crash")
        reserved = coordinator._reserve(
            database,
            LearnerScope(learner_id=learner_id, credential_id="test"),
            session_id,
            "work",
            body,
            turn_key,
            DOUBLE_LABEL,
            utc_now(),
        )
        assert isinstance(reserved, coordinator._Reserved)
        return turn_key, body

    def test_restart_fails_pending_turns_honestly_and_keeps_student_work(
        self, seeded_db_url: str
    ) -> None:
        settings = Settings(database_url=seeded_db_url)
        with TestClient(create_app(settings)) as first:
            learner_id, headers = bootstrap(first)
            session_id = start_session(first, headers)
            check_in(first, headers, session_id)
            database = Database(seeded_db_url)
            try:
                self._reserve_without_finishing(database, learner_id, session_id, "2x + 3 = 14", 1)
                assert state(first, headers, session_id)["pending_turn_id"] is not None
                ink = stroke(first, headers, session_id)
                steps_before = table_counts(database, learner_id)["steps"]
            finally:
                database.dispose()
        # The "process" restarted: a new app on the same file recovers pending work.
        with TestClient(create_app(settings)) as second:
            recovered = state(second, headers, session_id)
            assert recovered["pending_turn_id"] is None
            assert recovered["session"]["cancellation_epoch"] == 1
            events = second.get(f"/sessions/{session_id}/events", headers=headers).json()
            failed = [e for e in events if e["status"] == "failed"]
            assert len(failed) == 1
            assert [r["code"] for r in failed[0]["rejections"]] == ["restart_interrupted"]
            assert failed[0]["utterance"] is None and failed[0]["drawings"] == []
            assert failed[0]["student_input"]["step_id"]
            board = scene(second, headers, session_id)
            assert ink["object_id"] in [o["id"] for o in board["objects"]]
            database = Database(seeded_db_url)
            try:
                assert table_counts(database, learner_id)["steps"] == steps_before
            finally:
                database.dispose()
            # The committed check-in turn is untouched and a new current turn succeeds.
            assert events[0]["status"] == "committed"
            revision = recovered["session"]["revision"]
            current = post_turn(
                second, headers, session_id, "work", work_body("2x + 6 = 14", revision), key("n")
            ).json()
            assert current["status"] == "committed"

    def test_same_key_retry_after_restart_finishes_the_turn_exactly_once(
        self, seeded_db_url: str
    ) -> None:
        settings = Settings(database_url=seeded_db_url)
        with TestClient(create_app(settings)) as first:
            learner_id, headers = bootstrap(first)
            session_id = start_session(first, headers)
            check_in(first, headers, session_id)
            database = Database(seeded_db_url)
            try:
                turn_key, body = self._reserve_without_finishing(
                    database, learner_id, session_id, "2x + 3 = 14", 1
                )
            finally:
                database.dispose()
        with TestClient(create_app(settings)) as second:
            database = Database(seeded_db_url)
            try:
                before = table_counts(database, learner_id)
                retry = post_turn(second, headers, session_id, "work", body.model_dump(), turn_key)
                assert retry.status_code == 200, retry.text
                assert retry.json()["status"] == "committed" and retry.json()["utterance"]
                again = post_turn(second, headers, session_id, "work", body.model_dump(), turn_key)
                assert again.json()["turn_id"] == retry.json()["turn_id"]
                assert again.json()["replayed"] is True
                after = table_counts(database, learner_id)
                assert after["turns"] == before["turns"]
                assert after["steps"] == before["steps"]
                assert after["hints"] == before["hints"] + 1
                assert state(second, headers, session_id)["pending_turn_id"] is None
            finally:
                database.dispose()

    def test_restart_without_pending_work_changes_nothing(self, seeded_db_url: str) -> None:
        settings = Settings(database_url=seeded_db_url)
        with TestClient(create_app(settings)) as first:
            _, headers = bootstrap(first)
            session_id = start_session(first, headers)
            check_in(first, headers, session_id)
            work(first, headers, session_id, "2x + 3 = 14", 1)
            before = state(first, headers, session_id)
        with TestClient(create_app(settings)) as second:
            assert state(second, headers, session_id) == before


class TestNewProblemLegibility:
    def _solve_first_problem(
        self, client: TestClient, headers: Headers, session_id: str
    ) -> tuple[dict, dict]:
        first_ink = stroke(client, headers, session_id, x=200.0)
        hint = work(client, headers, session_id, "2x + 3 = 14", 1)
        work(client, headers, session_id, "2x + 6 = 14", 2)
        second_ink = stroke(client, headers, session_id, x=500.0)
        solved = work(client, headers, session_id, "x = 4", 3)
        assert solved["current_problem"]["statement"] == "3(x - 2) = 12"
        assert hint["drawings"]
        return first_ink, second_ink

    def test_superseded_tutor_marks_leave_the_view_and_student_work_is_untouched(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        first_ink, second_ink = self._solve_first_problem(client, headers, session_id)
        board = scene(client, headers, session_id)
        tutor = [o for o in board["objects"] if o["author_role"] == "tutor"]
        assert [o["semantic_role"] for o in tutor if o["kind"] == "text"] == ["problem_statement"]
        assert [o["payload"]["text"] for o in tutor if o["kind"] == "text"] == ["3(x - 2) = 12"]
        # The second problem of the session says so, so clients can set earlier ink apart.
        (statement,) = [o for o in tutor if o["semantic_role"] == "problem_statement"]
        assert statement["payload"]["problem_number"] == 2
        # No two visible tutor objects share a position: nothing is overprinted.
        anchors = [
            (o["payload"].get("x"), o["payload"].get("y")) for o in tutor if o["kind"] == "text"
        ]
        assert len(anchors) == len(set(anchors))
        student_ids = {o["id"] for o in board["objects"] if o["author_role"] == "student"}
        assert student_ids == {first_ink["object_id"], second_ink["object_id"]}
        with database.transaction() as db:
            rows = {
                r.id: r
                for r in db.execute(
                    select(SceneObjectRow).where(SceneObjectRow.learner_id == learner_id)
                ).scalars()
            }
            # Retired tutor rows are kept (hidden), student rows are exactly as written.
            retired = [r for r in rows.values() if r.author_role == "tutor" and r.deleted_at]
            assert len(retired) >= 3
            for oid in student_ids:
                assert rows[oid].deleted_at is None and rows[oid].author_role == "student"
            ops = list(
                db.execute(
                    select(SceneOperationRow)
                    .where(SceneOperationRow.learner_id == learner_id)
                    .order_by(SceneOperationRow.seq)
                ).scalars()
            )
            retire_ops = [o for o in ops if o.kind == "erase_object" and o.author_role == "tutor"]
            assert {o.object_id for o in retire_ops} == {r.id for r in retired}
            assert all(o.move_id is None for o in retire_ops)
            assert [o.seq for o in ops] == list(range(1, len(ops) + 1))
            assert not any(o.author_role == "student" and o.kind == "erase_object" for o in ops)

    def test_undoing_the_latest_tutor_move_does_not_bring_back_an_old_statement(
        self, client: TestClient
    ) -> None:
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        self._solve_first_problem(client, headers, session_id)
        before = scene(client, headers, session_id)
        response = client.post(
            f"/sessions/{session_id}/scene/operations",
            json={
                "operation_id": key("undo"),
                "expected_scene_revision": before["scene_revision"],
                "action": {"op": "undo_tutor_move"},
            },
            headers=headers,
        )
        assert response.status_code in (200, 409), response.text
        after = scene(client, headers, session_id)
        texts = [
            o["payload"]["text"]
            for o in after["objects"]
            if o["author_role"] == "tutor" and o["kind"] == "text"
        ]
        assert texts in (["3(x - 2) = 12"], [])
        assert "2(x + 3) = 14" not in texts

    def test_student_steps_and_history_survive_the_transition(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        first_ink, _ = self._solve_first_problem(client, headers, session_id)
        # Student undo walks only the student's own history, which the transition never touched.
        board = scene(client, headers, session_id)
        assert board["student_undo_available"] is True
        undo = client.post(
            f"/sessions/{session_id}/scene/operations",
            json={
                "operation_id": key("sundo"),
                "expected_scene_revision": board["scene_revision"],
                "action": {"op": "undo"},
            },
            headers=headers,
        )
        assert undo.status_code == 200, undo.text
        with database.transaction() as db:
            assert (
                db.execute(
                    select(func.count())
                    .select_from(StepRow)
                    .where(StepRow.learner_id == learner_id)
                ).scalar_one()
                == 3
            )
            turn_statuses = set(
                db.execute(
                    select(TutorTurnRow.status).where(TutorTurnRow.learner_id == learner_id)
                ).scalars()
            )
        assert turn_statuses == {"committed"}
        assert first_ink["object_id"]
