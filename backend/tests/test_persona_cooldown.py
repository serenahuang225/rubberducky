"""Server-UTC seven-day persona rule, comfort override and accessibility preferences.

VAL-PERSONA-002/003/004 and the persistence half of VAL-PERSONA-006. Boundary cases drive the
real API with a controlled server clock on a migrated file-backed SQLite database. A
client-supplied clock or process time zone never reaches the rule.
"""

import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.database import Database
from app.db.models import PreferenceRow, TutorConfigurationRow
from app.db.repositories import ScopedRepository
from app.learner.pairing import LearnerScope
from app.learner.persona import _claim_change, select_persona
from app.main import create_app
from app.pedagogy.persona import APPEARANCES, COMFORT_OVERRIDES, PERSONALITIES, opener
from app.schemas.tutor import TutorConfigurationRequest
from app.tutor.state import persona_options
from tests.conftest import bootstrap
from tests.test_adaptive_policy import assert_not_shaming
from tests.test_tutor_turns import check_in, start_session, work

COOLDOWN = timedelta(seconds=604800)
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
ANIMAL_GENTLE = {"appearance": "animal", "personality": "gentle"}
ELDER_PLAYFUL = {"appearance": "older_adult", "personality": "playful"}
YOUNG_SASSY = {"appearance": "younger_adult", "personality": "mildly_sassy"}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    controlled = Clock(T0)
    monkeypatch.setattr("app.api.persona.utc_now", controlled)
    return controlled


def put_persona(client: TestClient, headers: dict[str, str], body: dict):
    return client.put("/me/tutor-configuration", json=body, headers=headers)


def get_persona(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get("/me/tutor-configuration", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def stored(database: Database, learner_id: str) -> TutorConfigurationRow:
    with database.transaction() as db:
        row = db.execute(
            select(TutorConfigurationRow).where(TutorConfigurationRow.learner_id == learner_id)
        ).scalar_one()
        db.expunge(row)
        return row


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestInitialSelectionAndAvailability:
    def test_initial_selection_records_server_utc_time_and_next_availability(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        # A client clock, even an absurd one, cannot influence the record: bodies reject it.
        assert (
            client.put(
                "/me/tutor-configuration",
                json={**ANIMAL_GENTLE, "chosen_at": "1999-01-01T00:00:00Z"},
                headers=headers,
            ).status_code
            == 422
        )
        response = put_persona(
            client, {**headers, "Date": "Mon, 01 Jan 1990 00:00:00 GMT"}, ANIMAL_GENTLE
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["outcome"] == "initial_selection"
        assert parse(body["chosen_at"]) == T0 == parse(body["last_changed_at"])
        assert parse(body["server_now"]) == T0
        assert body["change_cooldown_seconds"] == 604800
        assert body["persona_locked"] is True
        assert parse(body["next_change_available_at"]) == T0 + COOLDOWN
        assert (
            body["next_change_available_at"].endswith("Z")
            or "+00:00" in (body["next_change_available_at"])
        )

    def test_get_reports_the_same_lock_and_a_clear_absence_before_selection(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        missing = client.get("/me/tutor-configuration", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "persona_not_selected"
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + timedelta(days=3)
        state = get_persona(client, headers)
        assert state["outcome"] is None
        assert state["persona_locked"] is True
        assert parse(state["next_change_available_at"]) == T0 + COOLDOWN
        clock.now = T0 + COOLDOWN
        state = get_persona(client, headers)
        assert state["persona_locked"] is False
        assert state["next_change_available_at"] is None

    @pytest.mark.parametrize("appearance", APPEARANCES)
    @pytest.mark.parametrize("personality", PERSONALITIES)
    def test_all_twelve_pairs_are_valid_first_choices(
        self, client: TestClient, clock: Clock, appearance: str, personality: str
    ) -> None:
        _, headers = bootstrap(client)
        response = put_persona(
            client, headers, {"appearance": appearance, "personality": personality}
        )
        assert response.status_code == 200
        assert response.json()["appearance"] == appearance
        assert response.json()["personality"] == personality


class TestBoundary:
    """VAL-PERSONA-003: equivalent fresh fixtures just before, at and after the boundary."""

    @pytest.mark.parametrize(
        ("offset", "accepted"),
        [
            (timedelta(0), False),
            (timedelta(seconds=1), False),
            (COOLDOWN - timedelta(days=1), False),
            (COOLDOWN - timedelta(seconds=1), False),
            (COOLDOWN - timedelta(microseconds=1), False),
            (COOLDOWN, True),
            (COOLDOWN + timedelta(microseconds=1), True),
            (COOLDOWN + timedelta(seconds=1), True),
            (COOLDOWN + timedelta(days=40), True),
        ],
    )
    def test_effective_change_matrix(
        self,
        client: TestClient,
        database: Database,
        clock: Clock,
        offset: timedelta,
        accepted: bool,
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + offset
        response = put_persona(client, headers, ELDER_PLAYFUL)
        row = stored(database, learner_id)
        if accepted:
            assert response.status_code == 200, response.text
            assert response.json()["outcome"] == "changed"
            assert (row.appearance, row.personality) == ("older_adult", "playful")
            assert row.last_changed_at == T0 + offset
            assert parse(response.json()["next_change_available_at"]) == T0 + offset + COOLDOWN
        else:
            assert response.status_code == 409, response.text
            error = response.json()["error"]
            assert error["code"] == "persona_change_locked"
            assert (T0 + COOLDOWN).isoformat().replace("+00:00", "Z") in error["message"]
            assert int(response.headers["Retry-After"]) >= 1
            assert (row.appearance, row.personality) == ("animal", "gentle")
            assert row.last_changed_at == T0
        assert row.chosen_at == T0

    def test_single_axis_changes_are_effective_changes_too(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + timedelta(days=1)
        for body in (
            {"appearance": "older_adult", "personality": "gentle"},
            {"appearance": "animal", "personality": "playful"},
        ):
            assert put_persona(client, headers, body).status_code == 409

    def test_rejected_change_and_effective_change_keep_the_lock_accounting(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + COOLDOWN + timedelta(hours=5)
        changed = put_persona(client, headers, ELDER_PLAYFUL).json()
        assert parse(changed["last_changed_at"]) == clock.now
        # The successful change starts a new full wait; the first one's expiry is irrelevant.
        clock.now += COOLDOWN - timedelta(seconds=1)
        assert put_persona(client, headers, YOUNG_SASSY).status_code == 409
        clock.now += timedelta(seconds=1)
        assert put_persona(client, headers, YOUNG_SASSY).status_code == 200


class TestNoOpSemantics:
    def test_identical_selection_never_resets_availability_before_or_after_eligibility(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        before = stored(database, learner_id)

        clock.now = T0 + timedelta(days=2)
        early = put_persona(client, headers, ANIMAL_GENTLE)
        assert early.status_code == 200
        assert early.json()["outcome"] == "no_change"
        assert parse(early.json()["next_change_available_at"]) == T0 + COOLDOWN
        assert stored(database, learner_id).last_changed_at == before.last_changed_at

        clock.now = T0 + COOLDOWN + timedelta(days=2)
        late = put_persona(client, headers, ANIMAL_GENTLE)
        assert late.json()["outcome"] == "no_change"
        assert late.json()["persona_locked"] is False
        after = stored(database, learner_id)
        assert after.last_changed_at == before.last_changed_at == T0
        assert after.chosen_at == T0

        # The identical selection did not consume or restart eligibility.
        assert put_persona(client, headers, ELDER_PLAYFUL).status_code == 200

    def test_no_op_at_the_exact_boundary_does_not_start_a_new_lock(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + COOLDOWN
        assert put_persona(client, headers, ANIMAL_GENTLE).json()["outcome"] == "no_change"
        assert put_persona(client, headers, YOUNG_SASSY).status_code == 200

    def test_omitted_comfort_leaves_the_override_alone_on_a_no_op(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, {**YOUNG_SASSY, "comfort_override": "reduced_sass"})
        again = put_persona(client, headers, YOUNG_SASSY).json()
        assert again["comfort_override"] == "reduced_sass"
        assert again["comfort_changed"] is False


class TestRestartRefreshAndClocks:
    def test_selection_and_timestamp_survive_a_new_app_instance(
        self, seeded_db_url: str, clock: Clock
    ) -> None:
        with TestClient(create_app(Settings(database_url=seeded_db_url))) as first:
            _, headers = bootstrap(first)
            put_persona(first, headers, ELDER_PLAYFUL)
        with TestClient(create_app(Settings(database_url=seeded_db_url))) as second:
            clock.now = T0 + COOLDOWN - timedelta(seconds=1)
            state = get_persona(second, headers)
            assert (state["appearance"], state["personality"]) == ("older_adult", "playful")
            assert parse(state["chosen_at"]) == T0
            assert parse(state["next_change_available_at"]) == T0 + COOLDOWN
            assert put_persona(second, headers, ANIMAL_GENTLE).status_code == 409
            clock.now = T0 + COOLDOWN
            assert put_persona(second, headers, ANIMAL_GENTLE).status_code == 200

    def test_new_session_and_me_report_the_same_selection(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, YOUNG_SASSY)
        first = start_session(client, headers)
        second = start_session(client, headers)
        for session_id in (first, second):
            persona = client.get(f"/sessions/{session_id}/state", headers=headers).json()["persona"]
            assert persona["personality"] == "mildly_sassy"
            assert parse(persona["last_changed_at"]) == T0
        me = client.get("/me", headers=headers).json()["tutor_configuration"]
        assert parse(me["chosen_at"]) == T0

    @pytest.fixture
    def timezone_of(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
        def use(name: str) -> None:
            monkeypatch.setenv("TZ", name)
            time.tzset()

        yield use
        monkeypatch.undo()
        time.tzset()

    @pytest.mark.parametrize(
        "zone",
        ["UTC", "America/New_York", "Pacific/Auckland", "Asia/Kolkata", "Pacific/Kiritimati"],
    )
    def test_process_time_zone_does_not_change_the_rule(
        self,
        client: TestClient,
        clock: Clock,
        timezone_of: Callable[[str], None],
        zone: str,
    ) -> None:
        timezone_of(zone)
        _, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + COOLDOWN - timedelta(seconds=1)
        assert put_persona(client, headers, ELDER_PLAYFUL).status_code == 409
        clock.now = T0 + COOLDOWN
        assert put_persona(client, headers, ELDER_PLAYFUL).status_code == 200

    @pytest.mark.parametrize(
        "selected",
        [
            # Seven local days across US spring-forward (07:00Z on 2026-03-08).
            datetime(2026, 3, 4, 14, 30, tzinfo=UTC),
            # ...and across US fall-back (06:00Z on 2026-11-01).
            datetime(2026, 10, 28, 14, 30, tzinfo=UTC),
            # ...and across European spring-forward (01:00Z on 2026-03-29).
            datetime(2026, 3, 25, 0, 30, tzinfo=UTC),
        ],
    )
    def test_daylight_saving_transitions_do_not_stretch_the_wait(
        self,
        client: TestClient,
        clock: Clock,
        timezone_of: Callable[[str], None],
        selected: datetime,
    ) -> None:
        timezone_of("America/New_York")
        _, headers = bootstrap(client)
        clock.now = selected
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = selected + COOLDOWN - timedelta(seconds=1)
        assert put_persona(client, headers, ELDER_PLAYFUL).status_code == 409
        clock.now = selected + COOLDOWN
        accepted = put_persona(client, headers, ELDER_PLAYFUL)
        assert accepted.status_code == 200
        assert parse(accepted.json()["last_changed_at"]) == selected + COOLDOWN

    def test_equivalent_client_clock_headers_cannot_unlock_a_change(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        advanced = {
            **headers,
            "Date": (T0 + timedelta(days=30)).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "X-Client-Time": (T0 + timedelta(days=30)).isoformat(),
        }
        clock.now = T0 + timedelta(hours=1)
        assert put_persona(client, advanced, ELDER_PLAYFUL).status_code == 409


class TestConcurrency:
    @staticmethod
    def race(
        client: TestClient, headers: dict[str, str], bodies: list[dict]
    ) -> list[tuple[int, dict]]:
        barrier = threading.Barrier(len(bodies))
        results: list[tuple[int, dict]] = [(0, {})] * len(bodies)

        def submit(index: int) -> None:
            barrier.wait()
            response = client.put("/me/tutor-configuration", json=bodies[index], headers=headers)
            results[index] = (response.status_code, response.json())

        threads = [threading.Thread(target=submit, args=(i,)) for i in range(len(bodies))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def test_competing_effective_changes_cannot_both_consume_one_eligibility(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        for attempt in range(8):
            learner_id, headers = bootstrap(client, f"Racer {attempt}")
            clock.now = T0
            put_persona(client, headers, ANIMAL_GENTLE)
            clock.now = T0 + COOLDOWN + timedelta(minutes=attempt)
            results = self.race(client, headers, [ELDER_PLAYFUL, YOUNG_SASSY])
            statuses = sorted(status for status, _ in results)
            assert statuses == [200, 409], results
            winner = next(body for status, body in results if status == 200)
            assert winner["outcome"] == "changed"
            loser = next(body for status, body in results if status == 409)
            assert loser["error"]["code"] == "persona_change_locked"
            row = stored(database, learner_id)
            assert (row.appearance, row.personality) == (
                winner["appearance"],
                winner["personality"],
            )
            assert row.last_changed_at == clock.now

    def test_competing_first_selections_leave_one_initial_choice(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        for attempt in range(8):
            learner_id, headers = bootstrap(client, f"First {attempt}")
            clock.now = T0
            results = self.race(client, headers, [ELDER_PLAYFUL, YOUNG_SASSY])
            assert sorted(status for status, _ in results) == [200, 409], results
            winner = next(body for status, body in results if status == 200)
            assert winner["outcome"] == "initial_selection"
            row = stored(database, learner_id)
            assert (row.appearance, row.personality) == (
                winner["appearance"],
                winner["personality"],
            )
            assert row.chosen_at == row.last_changed_at == T0

    def test_identical_concurrent_requests_agree_without_a_second_lock(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        clock.now = T0 + COOLDOWN
        results = self.race(client, headers, [ELDER_PLAYFUL, ELDER_PLAYFUL])
        assert [status for status, _ in results] == [200, 200]
        assert sorted(body["outcome"] for _, body in results) == ["changed", "no_change"]
        assert stored(database, learner_id).last_changed_at == clock.now


class TestCompareAndSwap:
    def test_a_stale_eligible_view_cannot_claim_an_already_consumed_change(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        eligible = T0 + COOLDOWN
        scope = LearnerScope(learner_id=learner_id, credential_id="test")
        stale_session = database.new_session()
        winner_session = database.new_session()
        try:
            stale = ScopedRepository(db=stale_session, scope=scope)
            seen = stale_session.execute(
                select(TutorConfigurationRow).where(TutorConfigurationRow.learner_id == learner_id)
            ).scalar_one()
            winner = select_persona(
                ScopedRepository(db=winner_session, scope=scope),
                TutorConfigurationRequest.model_validate(ELDER_PLAYFUL),
                eligible,
            )
            winner_session.commit()
            assert winner.outcome == "changed"
            # The stale session still believes the change is available at the same instant.
            assert seen.last_changed_at == T0
            claimed = _claim_change(
                stale, seen, TutorConfigurationRequest.model_validate(YOUNG_SASSY), eligible
            )
            assert claimed is False
            stale_session.rollback()
        finally:
            stale_session.close()
            winner_session.close()
        row = stored(database, learner_id)
        assert (row.appearance, row.personality) == ("older_adult", "playful")


class TestComfortOverride:
    """VAL-PERSONA-004: an override never consumes, locks or resets the durable pair."""

    def test_override_is_available_during_a_lock_and_leaves_the_pair_and_timestamps(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, YOUNG_SASSY)
        before = stored(database, learner_id)
        clock.now = T0 + timedelta(hours=2)
        response = client.put(
            "/me/comfort-override", json={"comfort_override": "reduced_sass"}, headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["comfort_override"] == "reduced_sass"
        assert body["comfort_changed"] is True
        assert body["outcome"] == "no_change"
        assert parse(body["comfort_updated_at"]) == clock.now
        assert parse(body["next_change_available_at"]) == T0 + COOLDOWN
        after = stored(database, learner_id)
        assert (after.appearance, after.personality) == ("younger_adult", "mildly_sassy")
        assert after.chosen_at == before.chosen_at
        assert after.last_changed_at == before.last_changed_at

        # Toggling repeatedly never consumes a durable change, and one is still allowed at T+7d.
        for value in ("neutral_supportive", "none", "reduced_sass"):
            assert (
                client.put(
                    "/me/comfort-override", json={"comfort_override": value}, headers=headers
                ).status_code
                == 200
            )
        clock.now = T0 + COOLDOWN
        assert put_persona(client, headers, ELDER_PLAYFUL).status_code == 200

    def test_repeating_the_current_override_is_a_no_op(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, YOUNG_SASSY)
        first = client.put(
            "/me/comfort-override", json={"comfort_override": "neutral_supportive"}, headers=headers
        ).json()
        clock.now = T0 + timedelta(minutes=5)
        again = client.put(
            "/me/comfort-override", json={"comfort_override": "neutral_supportive"}, headers=headers
        ).json()
        assert again["comfort_changed"] is False
        assert again["comfort_updated_at"] == first["comfort_updated_at"]

    def test_next_turn_uses_the_override_while_the_durable_pair_stays_locked(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, YOUNG_SASSY)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        sassy = work(client, headers, session_id, "x + 3 = 7", 1)
        assert sassy["utterance"].startswith("Look at that, the equation behaved.")

        clock.now = T0 + timedelta(minutes=1)
        client.put(
            "/me/comfort-override", json={"comfort_override": "reduced_sass"}, headers=headers
        )
        reduced = work(client, headers, session_id, "2x + 6 = 14", 2)
        assert reduced["utterance"].startswith(opener("mildly_sassy", "reduced_sass", "success"))
        assert "Look at that" not in reduced["utterance"]

        client.put(
            "/me/comfort-override", json={"comfort_override": "neutral_supportive"}, headers=headers
        )
        persona = client.get(f"/sessions/{session_id}/state", headers=headers).json()["persona"]
        assert persona["personality"] == "mildly_sassy"
        assert persona["comfort_override"] == "neutral_supportive"
        assert opener("mildly_sassy", "neutral_supportive", "success") == "Nice work. "

    def test_a_locked_pair_change_bundled_with_comfort_applies_nothing(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, YOUNG_SASSY)
        clock.now = T0 + timedelta(days=1)
        response = put_persona(
            client, headers, {**ELDER_PLAYFUL, "comfort_override": "neutral_supportive"}
        )
        assert response.status_code == 409
        row = stored(database, learner_id)
        assert row.comfort_override == "none" and row.comfort_updated_at is None

    def test_comfort_without_an_initial_selection_is_a_clear_conflict(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        response = client.put(
            "/me/comfort-override", json={"comfort_override": "reduced_sass"}, headers=headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "persona_not_selected"

    def test_unknown_override_and_extra_fields_are_rejected(
        self, client: TestClient, clock: Clock
    ) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, ANIMAL_GENTLE)
        assert (
            client.put(
                "/me/comfort-override", json={"comfort_override": "sassier"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/me/comfort-override",
                json={"comfort_override": "none", "appearance": "animal"},
                headers=headers,
            ).status_code
            == 422
        )

    def test_every_style_and_override_combination_stays_respectful(self) -> None:
        tones = ("neutral", "correction", "success", "support")
        for personality in PERSONALITIES:
            for comfort in COMFORT_OVERRIDES:
                for tone in tones:
                    assert_not_shaming(opener(personality, comfort, tone))  # type: ignore[arg-type]
        assert persona_options().comfort_overrides == list(COMFORT_OVERRIDES)


class TestAccessibilityPreferences:
    def test_defaults_before_any_choice(self, client: TestClient) -> None:
        _, headers = bootstrap(client)
        body = client.get("/me/accessibility-preferences", headers=headers).json()
        assert body["animation"] == "system"
        assert body["sound_enabled"] is True
        assert body["haptics_enabled"] is True
        assert body["text_only"] is False
        assert body["captions_enabled"] is True
        assert body["updated_at"] is None

    def test_partial_updates_persist_independently_and_survive_restart(
        self, seeded_db_url: str, clock: Clock
    ) -> None:
        with TestClient(create_app(Settings(database_url=seeded_db_url))) as first:
            _, headers = bootstrap(first)
            put_persona(first, headers, YOUNG_SASSY)
            clock.now = T0 + timedelta(hours=3)
            response = first.patch(
                "/me/accessibility-preferences",
                json={"animation": "off", "sound_enabled": False},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert parse(response.json()["updated_at"]) == clock.now
            clock.now = T0 + timedelta(hours=4)
            first.patch("/me/accessibility-preferences", json={"text_only": True}, headers=headers)
        with TestClient(create_app(Settings(database_url=seeded_db_url))) as second:
            body = second.get("/me/accessibility-preferences", headers=headers).json()
            assert (body["animation"], body["sound_enabled"], body["text_only"]) == (
                "off",
                False,
                True,
            )
            assert body["haptics_enabled"] is True and body["captions_enabled"] is True
            persona = get_persona(second, headers)
            assert parse(persona["last_changed_at"]) == T0 == parse(persona["chosen_at"])
            assert persona["comfort_override"] == "none"

    def test_accessibility_edits_work_during_a_lock_and_never_touch_the_persona(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        learner_id, headers = bootstrap(client)
        put_persona(client, headers, ELDER_PLAYFUL)
        before = stored(database, learner_id)
        clock.now = T0 + timedelta(minutes=1)
        assert put_persona(client, headers, ANIMAL_GENTLE).status_code == 409
        for patch in (
            {"animation": "reduced"},
            {"haptics_enabled": False},
            {"captions_enabled": False, "text_only": True},
            {},
        ):
            response = client.patch("/me/accessibility-preferences", json=patch, headers=headers)
            assert response.status_code == 200, response.text
        after = stored(database, learner_id)
        assert (after.appearance, after.personality, after.comfort_override) == (
            before.appearance,
            before.personality,
            before.comfort_override,
        )
        assert after.chosen_at == before.chosen_at
        assert after.last_changed_at == before.last_changed_at
        assert after.comfort_updated_at is None
        clock.now = T0 + COOLDOWN
        assert put_persona(client, headers, ANIMAL_GENTLE).status_code == 200

    def test_invalid_values_nulls_and_unknown_fields_are_rejected_without_writes(
        self, client: TestClient, database: Database
    ) -> None:
        learner_id, headers = bootstrap(client)
        for bad in (
            {"animation": "confetti"},
            {"animation": None},
            {"sound_enabled": "loud"},
            {"text_only": None},
            {"streak_reminders": True},
        ):
            response = client.patch("/me/accessibility-preferences", json=bad, headers=headers)
            assert response.status_code == 422, bad
        with database.transaction() as db:
            keys = (
                db.execute(select(PreferenceRow.key).where(PreferenceRow.learner_id == learner_id))
                .scalars()
                .all()
            )
        assert not [k for k in keys if k.startswith("a11y_")]

    def test_only_comfort_endpoint_changes_comfort(self, client: TestClient, clock: Clock) -> None:
        _, headers = bootstrap(client)
        put_persona(client, headers, YOUNG_SASSY)
        assert (
            client.patch(
                "/me/accessibility-preferences",
                json={"comfort_override": "reduced_sass"},
                headers=headers,
            ).status_code
            == 422
        )


class TestLearnerScope:
    def test_other_learners_cannot_read_or_affect_a_locked_persona(
        self, client: TestClient, database: Database, clock: Clock
    ) -> None:
        ada_id, ada = bootstrap(client, "Ada demo")
        ben_id, ben = bootstrap(client, "Ben demo")
        put_persona(client, ada, YOUNG_SASSY)

        assert client.get("/me/tutor-configuration", headers=ben).status_code == 404
        assert client.get("/me/accessibility-preferences", headers=ben).json()["updated_at"] is None
        # Ben's first selection is his own initial choice and is not locked by Ada's record.
        assert put_persona(client, ben, ANIMAL_GENTLE).json()["outcome"] == "initial_selection"
        clock.now = T0 + timedelta(hours=1)
        client.put("/me/comfort-override", json={"comfort_override": "reduced_sass"}, headers=ben)
        client.patch("/me/accessibility-preferences", json={"text_only": True}, headers=ben)

        ada_row = stored(database, ada_id)
        assert ada_row.comfort_override == "none"
        assert (ada_row.appearance, ada_row.personality) == ("younger_adult", "mildly_sassy")
        assert client.get("/me/accessibility-preferences", headers=ada).json()["text_only"] is False
        assert ben_id != ada_id

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("GET", "/me/tutor-configuration", None),
            ("PUT", "/me/tutor-configuration", ANIMAL_GENTLE),
            ("PUT", "/me/comfort-override", {"comfort_override": "none"}),
            ("GET", "/me/accessibility-preferences", None),
            ("PATCH", "/me/accessibility-preferences", {"text_only": True}),
        ],
    )
    def test_routes_require_a_credential(
        self, client: TestClient, method: str, path: str, body: dict | None
    ) -> None:
        response = client.request(method, path, json=body)
        assert response.status_code == 401
