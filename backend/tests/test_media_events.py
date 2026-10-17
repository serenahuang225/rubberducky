"""Bounded, uncertain, learner-scoped media events (VAL-MEDIA-002, VAL-MEDIA-003).

The deterministic fixtures run through the real routes and migrated SQLite. Nothing here
performs transcription or perception: transcripts and recognition are explicitly
``simulated`` fixtures, and real (device-sourced) recognition reports ``unavailable``.
"""

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.database import Database
from app.db.models import (
    MasteryEstimateRow,
    MediaEventRow,
    ObservationRow,
    StepRow,
    TutorTurnRow,
)
from app.main import create_app
from app.multimodal import limits
from tests.conftest import bootstrap


@pytest.fixture
def media_client(seeded_db_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(database_url=seeded_db_url))) as test_client:
        yield test_client


def _start(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post("/sessions", json={}, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _scope(client: TestClient, headers: dict[str, str], session_id: str) -> tuple[int, int]:
    state = client.get(f"/sessions/{session_id}/state", headers=headers).json()
    return state["session"]["revision"], state["session"]["cancellation_epoch"]


def _event(
    client: TestClient, headers: dict[str, str], session_id: str, body: dict[str, Any]
) -> Any:
    revision, epoch = _scope(client, headers, session_id)
    payload = {
        "schema_version": "media-event-request.v1",
        "expected_revision": revision,
        "observed_epoch": epoch,
        "source": "simulated",
        **body,
    }
    return client.post(f"/sessions/{session_id}/media/events", json=payload, headers=headers)


def _transcript(event_id: str, utterance: str, seq: int, phase: str, text: str = "x = 4") -> dict:
    return {
        "kind": "transcript",
        "event_id": event_id,
        "utterance_id": utterance,
        "sequence": seq,
        "phase": phase,
        "text": text,
    }


def _image(event_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "kind": "image_snapshot",
        "event_id": event_id,
        "orientation": "work_facing",
        "trigger": "explicit_capture",
        "mime": "image/jpeg",
        "width": 640,
        "height": 480,
        "byte_size": 40_000,
        **overrides,
    }


def _counts(database: Database, learner_id: str) -> dict[str, int]:
    with database.transaction() as db:
        return {
            name: int(
                db.execute(
                    select(func.count()).select_from(model).where(model.learner_id == learner_id)
                ).scalar_one()
            )
            for name, model in (
                ("observations", ObservationRow),
                ("steps", StepRow),
                ("turns", TutorTurnRow),
                ("mastery", MasteryEstimateRow),
            )
        }


def test_capabilities_are_honest_and_need_a_paired_learner(media_client: TestClient) -> None:
    assert media_client.get("/media/capabilities").status_code == 401
    _, headers = bootstrap(media_client)
    body = media_client.get("/media/capabilities", headers=headers).json()
    assert body["perception"]["status"] == "unavailable"
    assert body["transcription"]["status"] == "unavailable"
    assert body["speech_interruption"]["acoustic_barge_in"] is False
    assert body["defaults"] == {
        "raw_media_stored": False,
        "raw_media_logged": False,
        "transcripts_retained": False,
        "provider_transmission": "none_configured",
    }
    assert body["fixtures"]["enabled"] is True
    assert body["limits"]["max_image_bytes"] == limits.MAX_IMAGE_BYTES
    assert "no provider" in " ".join(body["disclosures"]["transmitted"]).lower()


def test_interim_stays_provisional_and_a_revised_interim_replaces_it(
    media_client: TestClient,
) -> None:
    _, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    first = _event(
        media_client, headers, session["id"], _transcript("e-int-0001", "u1", 0, "interim")
    )
    revised = _event(
        media_client,
        headers,
        session["id"],
        _transcript("e-int-0002", "u1", 1, "interim", "x = 4."),
    )
    assert first.status_code == revised.status_code == 200
    for response in (first, revised):
        body = response.json()
        assert body["status"] == "provisional"
        assert body["simulated"] is True
        assert body["assessment_effect"] == "none" and body["evidence_recorded"] is False
    older = _event(
        media_client, headers, session["id"], _transcript("e-int-0003", "u1", 0, "interim")
    ).json()
    assert older["status"] == "ignored_late"


def test_final_is_accepted_once_never_assessed_and_duplicates_are_idempotent(
    media_client: TestClient, database: Database
) -> None:
    learner_id, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    before = _counts(database, learner_id)
    final = _event(
        media_client, headers, session["id"], _transcript("e-fin-0001", "u9", 3, "final")
    )
    assert final.status_code == 200
    assert final.json()["status"] == "final_accepted"
    assert final.json()["requires_confirmation"] is True
    # The same event retried (lost acknowledgment) replays the stored outcome.
    again = _event(
        media_client, headers, session["id"], _transcript("e-fin-0001", "u9", 3, "final")
    )
    assert again.json()["status"] == "final_accepted" and again.json()["replayed"] is True
    # A second final for the same utterance is a duplicate, not a second submission.
    duplicate = _event(
        media_client, headers, session["id"], _transcript("e-fin-0002", "u9", 4, "final")
    )
    assert duplicate.json()["status"] == "duplicate_final"
    # Late interim after final cannot reopen the utterance.
    late = _event(
        media_client, headers, session["id"], _transcript("e-int-0009", "u9", 5, "interim")
    )
    assert late.json()["status"] == "ignored_late"
    assert _counts(database, learner_id) == before
    with database.transaction() as db:
        finals = db.execute(
            select(func.count()).select_from(MediaEventRow).where(MediaEventRow.final_key == "u9")
        ).scalar_one()
    assert finals == 1


def test_reusing_an_event_id_with_different_content_is_a_conflict(
    media_client: TestClient,
) -> None:
    _, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    ok = _event(
        media_client, headers, session["id"], _transcript("e-same-0001", "u1", 0, "interim")
    )
    assert ok.status_code == 200
    changed = _event(
        media_client,
        headers,
        session["id"],
        _transcript("e-same-0001", "u1", 0, "interim", "x = 5"),
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_conflict"


def test_stale_revision_and_interrupted_epoch_reject_late_voice(
    media_client: TestClient,
) -> None:
    _, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    revision, epoch = _scope(media_client, headers, session["id"])
    base = {
        "schema_version": "media-event-request.v1",
        "source": "simulated",
        **_transcript("e-late-0001", "u2", 0, "interim"),
    }
    url = f"/sessions/{session['id']}/media/events"
    stale_revision = media_client.post(
        url,
        json={**base, "expected_revision": revision + 3, "observed_epoch": epoch},
        headers=headers,
    )
    assert stale_revision.status_code == 409
    assert stale_revision.json()["error"]["code"] == "stale_revision"
    interrupt = media_client.post(
        f"/sessions/{session['id']}/interrupt",
        json={
            "schema_version": "interrupt-request.v1",
            "observed_epoch": epoch,
            "reason": "speech_barge_in",
        },
        headers=headers,
    )
    assert interrupt.status_code == 200
    late = media_client.post(
        url, json={**base, "expected_revision": revision, "observed_epoch": epoch}, headers=headers
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "stale_epoch"
    fresh = _event(
        media_client, headers, session["id"], _transcript("e-late-0002", "u3", 0, "interim")
    )
    assert fresh.status_code == 200


def test_unconfigured_transcription_and_perception_are_unavailable_never_canned(
    media_client: TestClient,
) -> None:
    _, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    device_voice = _event(
        media_client,
        headers,
        session["id"],
        {**_transcript("e-dev-0001", "u1", 0, "final"), "source": "device"},
    )
    assert device_voice.status_code == 409
    assert device_voice.json()["error"]["code"] == "transcription_unavailable"
    device_image = _event(
        media_client, headers, session["id"], {**_image("e-dev-0002"), "source": "device"}
    )
    assert device_image.status_code == 200
    body = device_image.json()
    assert body["status"] == "perception_unavailable"
    assert body["candidates"] == []
    assert body["simulated"] is False
    assert body["requires_confirmation"] is False


def test_fixture_recognition_is_uncertain_synthetic_and_changes_no_estimate(
    media_client: TestClient, database: Database
) -> None:
    learner_id, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    before = _counts(database, learner_id)
    response = _event(media_client, headers, session["id"], _image("e-fix-0001"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "candidates_uncertain"
    assert body["simulated"] is True
    assert body["requires_confirmation"] is True
    assert len(body["candidates"]) >= 2
    for candidate in body["candidates"]:
        assert candidate["status"] == "uncertain"
        assert candidate["editable"] is True and candidate["synthetic"] is True
        assert candidate["confidence"] < 0.6
    assert body["assessment_effect"] == "none"
    assert _counts(database, learner_id) == before


def test_weak_context_gets_a_clarification_prompt_and_no_inference(
    media_client: TestClient, database: Database
) -> None:
    learner_id, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    before = _counts(database, learner_id)
    for index, signal in enumerate(("silence", "voice_level", "expression_cue", "gaze_cue")):
        response = _event(
            media_client,
            headers,
            session["id"],
            {"kind": "weak_context", "event_id": f"e-weak-000{index}", "signal": signal},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "clarification_prompt"
        assert body["candidates"] == [] and body["evidence_recorded"] is False
        message = body["message"].lower()
        for banned in ("tired", "frustrat", "bored", "disabilit", "anxious", "identity"):
            assert banned not in message
    assert _counts(database, learner_id) == before


def test_image_bounds_reject_oversized_and_excessive_events(media_client: TestClient) -> None:
    _, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    too_big = _event(
        media_client,
        headers,
        session["id"],
        _image("e-big-0001", byte_size=limits.MAX_IMAGE_BYTES + 1),
    )
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "media_too_large"
    wide = _event(
        media_client, headers, session["id"], _image("e-big-0002", width=limits.MAX_IMAGE_EDGE + 1)
    )
    assert wide.status_code == 413
    blob = base64.b64encode(b"\x00" * (limits.MAX_IMAGE_BYTES + 10)).decode()
    inline = _event(
        media_client,
        headers,
        session["id"],
        _image("e-big-0003", byte_size=100, image_base64=blob),
    )
    assert inline.status_code == 413
    for index in range(limits.MAX_IMAGE_EVENTS_PER_MINUTE):
        assert (
            _event(media_client, headers, session["id"], _image(f"e-rate-{index:04d}")).status_code
            == 200
        )
    limited = _event(media_client, headers, session["id"], _image("e-rate-9999"))
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "media_rate_limited"


def test_per_session_image_count_is_bounded(media_client: TestClient, database: Database) -> None:
    learner_id, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    revision, epoch = _scope(media_client, headers, session["id"])
    with database.transaction() as db:
        from datetime import timedelta

        from app.clock import utc_now

        old = utc_now() - timedelta(hours=1)
        for index in range(limits.MAX_IMAGE_EVENTS_PER_SESSION):
            db.add(
                MediaEventRow(
                    learner_id=learner_id,
                    event_id=f"seed-{index:04d}",
                    session_id=session["id"],
                    kind="image_snapshot",
                    source="simulated",
                    status="candidates_uncertain",
                    base_revision=revision,
                    base_epoch=epoch,
                    request_hash="0" * 64,
                    result={},
                    created_at=old,
                )
            )
    response = _event(media_client, headers, session["id"], _image("e-cap-0001"))
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "media_session_limit"


def test_foreign_and_unknown_sessions_are_not_found_and_leave_no_trace(
    media_client: TestClient, database: Database
) -> None:
    ada_id, ada = bootstrap(media_client, "Ada")
    ben_id, ben = bootstrap(media_client, "Ben")
    session = _start(media_client, ada)
    url = f"/sessions/{session['id']}/media/events"
    payload = {
        "schema_version": "media-event-request.v1",
        "expected_revision": 0,
        "observed_epoch": 0,
        "source": "simulated",
        **_transcript("e-foreign-01", "u1", 0, "interim"),
    }
    assert media_client.post(url, json=payload, headers=ben).status_code == 404
    assert media_client.post(url, json=payload).status_code == 401
    with database.transaction() as db:
        rows = db.execute(select(func.count()).select_from(MediaEventRow)).scalar_one()
    assert rows == 0
    assert ada_id != ben_id


def test_fixtures_can_be_disabled_and_real_sources_stay_honest(
    seeded_db_url: str,
) -> None:
    settings = Settings(database_url=seeded_db_url, tutor_media_fixtures_enabled=False)
    with TestClient(create_app(settings)) as client:
        _, headers = bootstrap(client)
        session = _start(client, headers)
        capabilities = client.get("/media/capabilities", headers=headers).json()
        assert capabilities["fixtures"]["enabled"] is False
        refused = _event(
            client, headers, session["id"], _transcript("e-off-0001", "u1", 0, "interim")
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "fixtures_disabled"


def test_unsupported_shapes_are_422_with_safe_field_diagnostics(
    media_client: TestClient,
) -> None:
    _, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    response = _event(
        media_client,
        headers,
        session["id"],
        _image("e-bad-0001", trigger="continuous_stream", mime="video/mp4"),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_version"] == "error.v1"
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["fields"]
    assert "continuous_stream" not in response.text


def test_media_rows_hold_metadata_only_and_go_with_the_session(
    media_client: TestClient, database: Database, seeded_db_url: str
) -> None:
    learner_id, headers = bootstrap(media_client)
    session = _start(media_client, headers)
    text = "private-spoken-words"
    assert (
        _event(
            media_client, headers, session["id"], _transcript("e-meta-0001", "u1", 0, "final", text)
        ).status_code
        == 200
    )
    db_path = Path(seeded_db_url.removeprefix("sqlite:///"))
    assert text.encode() not in db_path.read_bytes()
    removal = media_client.delete(f"/sessions/{session['id']}", headers=headers)
    assert removal.status_code == 200
    with database.transaction() as db:
        remaining = db.execute(
            select(func.count())
            .select_from(MediaEventRow)
            .where(MediaEventRow.learner_id == learner_id)
        ).scalar_one()
    assert remaining == 0
