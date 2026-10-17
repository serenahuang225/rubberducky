from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import Database
from app.db.migrate import upgrade_to_head
from app.db.seed import seed_database
from app.main import create_app
from tests.provider_fixtures import no_network  # noqa: F401 - shared pytest fixture


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """A real file-backed SQLite database migrated with Alembic (never create_all)."""
    url = f"sqlite:///{tmp_path / 'tutor.db'}"
    upgrade_to_head(url)
    return url


@pytest.fixture
def seeded_db_url(db_url: str) -> str:
    database = Database(db_url)
    try:
        with database.transaction() as db:
            seed_database(db)
    finally:
        database.dispose()
    return db_url


@pytest.fixture
def database(seeded_db_url: str) -> Iterator[Database]:
    database = Database(seeded_db_url)
    yield database
    database.dispose()


@pytest.fixture
def client(seeded_db_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(database_url=seeded_db_url))) as test_client:
        yield test_client


def bootstrap(client: TestClient, name: str = "Demo learner") -> tuple[str, dict[str, str]]:
    """Pair a new fictional learner; returns (learner_id, auth headers)."""
    response = client.post("/demo/bootstrap", json={"display_name": name})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["learner"]["id"], {"Authorization": f"Bearer {body['access_token']}"}
