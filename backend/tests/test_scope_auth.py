import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import PUBLIC_ROUTES
from app.clock import utc_now
from app.config import Settings
from app.db.database import Database
from app.db.models import CredentialRow, SessionRow
from app.db.repositories import NotInScopeError, ScopedRepository
from app.db.seed import DEMO_LEARNER_ADA, DEMO_LEARNER_BEN, seed_uuid
from app.learner.pairing import LearnerScope, issue_pairing_code, revoke_all_for_learner
from app.main import create_app
from tests.conftest import bootstrap

ADA_SEED_SESSION = seed_uuid("session:ada:1")


def pair_seeded(database: Database, client: TestClient, learner_id: str) -> dict[str, str]:
    with database.transaction() as db:
        code = issue_pairing_code(db, learner_id, utc_now(), timedelta(minutes=5))
    response = client.post("/pairing/redeem", json={"code": code})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def session_snapshot(database: Database, session_id: str) -> tuple[str, int, object]:
    with database.transaction() as db:
        row = db.get(SessionRow, session_id)
        assert row is not None
        return row.status, row.revision, row.ended_at


def test_bootstrap_labels_a_fictional_empty_learner_and_stores_only_a_digest(
    client: TestClient, database: Database
) -> None:
    response = client.post("/demo/bootstrap", json={"display_name": "Cam"})
    assert response.status_code == 201
    body = response.json()
    assert body["learner"]["is_fictional"] is True
    assert body["learner"]["provenance"] == "submitted"
    assert "fictional" in body["notice"].lower()
    token = body["access_token"]
    assert token.startswith("rdk_") and len(token) > 40
    with database.transaction() as db:
        hashes = list(db.execute(select(CredentialRow.token_hash)).scalars())
    assert token not in hashes
    history = client.get("/me/history", headers={"Authorization": f"Bearer {token}"}).json()
    assert history["sessions"] == [] and history["observations"] == []


def test_bootstrap_can_be_disabled(seeded_db_url: str) -> None:
    settings = Settings(database_url=seeded_db_url, demo_bootstrap_enabled=False)
    with TestClient(create_app(settings)) as client:
        response = client.post("/demo/bootstrap", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "bootstrap_disabled"


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
        "Bearer not-a-token",
        "Bearer rdk_" + "A" * 43,
        "Bearer rdk_" + "A" * 400,
    ],
    ids=["missing", "empty", "no-token", "blank", "basic", "malformed", "unknown", "oversized"],
)
def test_missing_or_malformed_credentials_are_rejected(
    client: TestClient, header: str | None
) -> None:
    headers = {} if header is None else {"Authorization": header}
    for method, path in [("GET", "/me"), ("GET", "/me/history"), ("GET", "/sessions")]:
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401
        assert response.json() == {
            "schema_version": "error.v1",
            "error": {
                "code": "unauthenticated",
                "message": "A valid paired bearer credential is required.",
            },
        }
        assert response.headers["www-authenticate"] == "Bearer"


def test_revoked_credentials_fail_and_other_devices_keep_working(client: TestClient) -> None:
    _, headers = bootstrap(client)
    assert client.get("/me", headers=headers).status_code == 200
    assert client.post("/auth/revoke", headers=headers).status_code == 204
    assert client.get("/me", headers=headers).status_code == 401
    assert client.post("/sessions", json={}, headers=headers).status_code == 401


def test_cli_revoke_disables_every_credential_of_a_learner(
    client: TestClient, database: Database
) -> None:
    first = pair_seeded(database, client, DEMO_LEARNER_BEN)
    second = pair_seeded(database, client, DEMO_LEARNER_BEN)
    with database.transaction() as db:
        assert revoke_all_for_learner(db, DEMO_LEARNER_BEN, utc_now()) == 2
    assert client.get("/me", headers=first).status_code == 401
    assert client.get("/me", headers=second).status_code == 401


def test_pairing_codes_are_one_time_and_expire(client: TestClient, database: Database) -> None:
    with database.transaction() as db:
        code = issue_pairing_code(db, DEMO_LEARNER_ADA, utc_now(), timedelta(minutes=5))
        expired = issue_pairing_code(
            db, DEMO_LEARNER_ADA, utc_now() - timedelta(minutes=10), timedelta(minutes=5)
        )
    assert client.post("/pairing/redeem", json={"code": code.lower()}).status_code == 200
    reused = client.post("/pairing/redeem", json={"code": code})
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "invalid_pairing_code"
    assert client.post("/pairing/redeem", json={"code": expired}).status_code == 400
    assert client.post("/pairing/redeem", json={"code": "ZZZZZZZZZZZZ"}).status_code == 400


def test_seeded_learner_sees_own_fictional_history_after_pairing(
    client: TestClient, database: Database
) -> None:
    headers = pair_seeded(database, client, DEMO_LEARNER_ADA)
    me = client.get("/me", headers=headers).json()
    assert me["learner"]["id"] == DEMO_LEARNER_ADA
    assert me["tutor_configuration"]["personality"] == "gentle"
    history = client.get("/me/history", headers=headers).json()
    assert [s["id"] for s in history["sessions"]] == [ADA_SEED_SESSION]
    records = [*history["sessions"], *history["observations"], *history["hints"]]
    assert records and all(r["provenance"] == "fictional_seed" for r in records)

    created = client.post("/sessions", json={"goal": "Return visit"}, headers=headers).json()
    assert created["provenance"] == "submitted"
    provenances = {
        s["id"]: s["provenance"]
        for s in client.get("/me/history", headers=headers).json()["sessions"]
    }
    assert provenances == {ADA_SEED_SESSION: "fictional_seed", created["id"]: "submitted"}


def test_two_learners_cannot_read_or_mutate_each_others_records(
    client: TestClient, database: Database
) -> None:
    a_id, a = bootstrap(client, "Learner A")
    b_id, b = bootstrap(client, "Learner B")
    a_session = client.post("/sessions", json={"goal": "A's goal"}, headers=a).json()
    assert a_session["learner_id"] == a_id
    before = session_snapshot(database, a_session["id"])

    for method, path in [
        ("GET", f"/sessions/{a_session['id']}"),
        ("POST", f"/sessions/{a_session['id']}/end"),
    ]:
        response = client.request(method, path, headers=b)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert a_session["goal"] not in response.text
    # A record that does not exist at all gets the identical response (no existence oracle).
    missing = client.get("/sessions/does-not-exist", headers=b)
    assert missing.status_code == 404
    assert missing.json() == client.get(f"/sessions/{a_session['id']}", headers=b).json()
    assert session_snapshot(database, a_session["id"]) == before

    assert client.get("/sessions", headers=b).json() == []
    b_history = client.get("/me/history", headers=b).json()
    assert b_history["learner"]["id"] == b_id
    assert b_history["sessions"] == []
    assert client.get("/me", headers=b).json()["learner"]["id"] == b_id

    # Seeded history of another learner is equally unreachable.
    assert client.get(f"/sessions/{ADA_SEED_SESSION}", headers=b).status_code == 404
    assert client.post(f"/sessions/{ADA_SEED_SESSION}/end", headers=b).status_code == 404

    # Own access still works.
    assert client.get(f"/sessions/{a_session['id']}", headers=a).status_code == 200
    ended = client.post(f"/sessions/{a_session['id']}/end", headers=a).json()
    assert ended["status"] == "ended" and ended["revision"] == 1


def test_client_supplied_learner_id_in_a_body_is_rejected_without_effects(
    client: TestClient, database: Database
) -> None:
    _, b = bootstrap(client, "Learner B")
    with database.transaction() as db:
        before = list(db.execute(select(SessionRow.id)).scalars())
    response = client.post("/sessions", json={"learner_id": DEMO_LEARNER_ADA}, headers=b)
    assert response.status_code == 422
    with database.transaction() as db:
        assert list(db.execute(select(SessionRow.id)).scalars()) == before


def test_repository_rejects_nested_references_outside_scope(database: Database) -> None:
    with database.transaction() as db:
        ben = ScopedRepository(db, LearnerScope(learner_id=DEMO_LEARNER_BEN, credential_id="t"))
        with pytest.raises(NotInScopeError):
            ben.require_session(ADA_SEED_SESSION)
        with pytest.raises(NotInScopeError):
            ben.require_attempt(seed_uuid("attempt:ada:1"))
        assert ben.history().sessions == []


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _operations() -> list[tuple[str, str, dict[str, object]]]:
    """Every documented operation, taken from the public OpenAPI schema."""
    schema = create_app(Settings(database_url="sqlite:///:memory:")).openapi()
    return sorted(
        (method.upper(), path, operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    )


def _route_matrix() -> list[tuple[str, str]]:
    return [(method, path) for method, path, _ in _operations()]


def test_every_non_public_route_requires_the_scope_guard(seeded_db_url: str) -> None:
    """Regression guard: routes added later must use the scope guard or be listed public."""
    client = TestClient(create_app(Settings(database_url=seeded_db_url)))
    guarded = 0
    for method, path, operation in _operations():
        if (method, path) in PUBLIC_ROUTES:
            assert "security" not in operation, f"{method} {path} is public but asks for auth"
            continue
        # The bearer scheme is only reachable through require_learner_scope.
        assert operation.get("security") == [{"HTTPBearer": []}], f"{method} {path}"
        probe = re.sub(r"\{[^}]+\}", "probe-id", path)
        response = client.request(method, probe, json={})
        assert response.status_code == 401, f"{method} {path}"
        assert response.json()["error"]["code"] == "unauthenticated"
        guarded += 1
    assert guarded >= 6
    assert {(m, p) for m, p in _route_matrix() if (m, p) in PUBLIC_ROUTES} == PUBLIC_ROUTES


def test_no_route_accepts_a_learner_id_or_exposes_unauthenticated_history() -> None:
    for method, path in _route_matrix():
        assert "learner" not in path.lower(), path
        if "history" in path:
            assert (method, path) not in PUBLIC_ROUTES


def test_unmigrated_database_reports_an_honest_error(tmp_path: Path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'empty.db'}")
    with TestClient(create_app(settings)) as client:
        response = client.post("/demo/bootstrap", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
