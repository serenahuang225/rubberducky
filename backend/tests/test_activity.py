import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.activity import ActivityLog, ActivityMiddleware, activity
from app.inference.events import EventRecorder


def test_live_activity_is_correlated_and_excludes_payloads(tmp_path):
    path = tmp_path / "activity.jsonl"
    log = ActivityLog(str(path))
    app = FastAPI()
    app.add_middleware(ActivityMiddleware, log=log)

    @app.post("/turns/{turn_id}")
    def turn(turn_id: str):
        activity("provider.request", provider="claude", model="test-model")
        EventRecorder().emit("delta", text="private model output")
        return {"access_token": "private-response"}

    with TestClient(app) as client:
        response = client.post(
            "/turns/private-id?token=private-query",
            json={"message": "private student text"},
            headers={"Authorization": "Bearer private-header"},
        )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["event"] for row in rows] == [
        "http.started",
        "provider.request",
        "provider.delta",
        "http.completed",
    ]
    assert {row["request_id"] for row in rows} == {response.headers["x-request-id"]}
    assert rows[-1]["route"] == "/turns/{turn_id}"
    assert rows[-1]["status"] == 200
    assert "private" not in path.read_text()
    log.close()


def test_unwritable_log_does_not_break_requests(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    log = ActivityLog(str(blocked / "activity.jsonl"))
    log.write("test", "id")
    log.close()


def test_activity_redacts_sensitive_fields(tmp_path):
    path = tmp_path / "activity.jsonl"
    log = ActivityLog(str(path))
    log.write("test", "id", api_key="private-secret")
    assert "private-secret" not in path.read_text()
    log.close()
