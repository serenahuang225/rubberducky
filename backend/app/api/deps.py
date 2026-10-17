"""Request-scoped database sessions and the learner scope guard.

Every learner-data route must depend on :func:`require_learner_scope` (directly or through
:data:`ScopedRepo`). The only unauthenticated routes are listed in :data:`PUBLIC_ROUTES`;
a regression test fails if any other route can be reached without a credential.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DbSession

from app.api.errors import unauthenticated
from app.config import Settings
from app.db.database import Database
from app.db.repositories import ScopedRepository
from app.learner.pairing import LearnerScope, resolve_token

PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/health/model"),
        ("POST", "/demo/bootstrap"),
        ("POST", "/pairing/redeem"),
    }
)

_bearer = HTTPBearer(auto_error=False, description="Paired demo learner credential")


def get_settings_dep(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not configured")
    return settings


def get_database(request: Request) -> Database:
    database = request.app.state.database
    if not isinstance(database, Database):
        raise RuntimeError("Application database is not configured")
    return database


def get_db(database: Annotated[Database, Depends(get_database)]) -> Iterator[DbSession]:
    """One short-lived session per request. Routes commit explicitly; anything else rolls back."""
    session = database.new_session()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


DbDep = Annotated[DbSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def require_learner_scope(
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> LearnerScope:
    if credentials is None or not credentials.credentials:
        raise unauthenticated()
    scope = resolve_token(db, credentials.credentials)
    if scope is None:
        raise unauthenticated()
    return scope


ScopeDep = Annotated[LearnerScope, Depends(require_learner_scope)]


def get_scoped_repository(db: DbDep, scope: ScopeDep) -> ScopedRepository:
    return ScopedRepository(db=db, scope=scope)


ScopedRepo = Annotated[ScopedRepository, Depends(get_scoped_repository)]
