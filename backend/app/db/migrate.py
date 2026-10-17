"""Programmatic Alembic helpers shared by the CLI and tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db.database import make_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # ConfigParser interpolates "%", which can appear in URL-encoded passwords.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade_to_head(url: str) -> str:
    make_engine(url, create_parent=True).dispose()
    command.upgrade(alembic_config(url), "head")
    revision = current_revision(url)
    if revision is None:
        raise RuntimeError("migration finished without a recorded revision")
    return revision


def head_revision(url: str) -> str:
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    if head is None:
        raise RuntimeError("no Alembic head revision found")
    return head


def current_revision(url: str) -> str | None:
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
