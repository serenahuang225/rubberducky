"""Engine and session factory. SQLite foreign keys are enabled on every new connection."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def sqlite_file_path(url: str) -> Path | None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        return None
    if parsed.database == ":memory:" or parsed.database.startswith("file:"):
        return None
    return Path(parsed.database)


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def make_engine(url: str, *, create_parent: bool = False) -> Engine:
    path = sqlite_file_path(url)
    if path is not None and create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    is_sqlite = make_url(url).get_backend_name() == "sqlite"
    connect_args: dict[str, Any] = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


class Database:
    """Owns one engine and hands out short-lived sessions (one per request or command)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = make_engine(url)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    def new_session(self) -> Session:
        return self._factory()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Commit on success; roll back every write in the block on any exception."""
        session = self._factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
