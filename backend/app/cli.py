"""Local administrative CLI: migrate, seed, pair, revoke and inspect history.

Trust boundary: this CLI reads and writes the database file directly with no credential
checks. Anyone able to run it can already read the file, so it is a local operator tool and
is never exposed over HTTP. Pairing codes it prints are one-time and short-lived; bearer
tokens are never printed.

Run from the repository root:
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli migrate
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select

from app.clock import utc_now
from app.config import get_settings
from app.db.database import Database
from app.db.migrate import upgrade_to_head
from app.db.models import Base, LearnerRow
from app.db.repositories import MAX_HISTORY_ITEMS, ScopedRepository
from app.db.seed import DEMO_LEARNERS, SEED_VERSION, seed_database
from app.learner.pairing import (
    LearnerScope,
    PairingError,
    issue_pairing_code,
    revoke_all_for_learner,
)


def _resolve_learner(database: Database, learner: str) -> str:
    learner_id = DEMO_LEARNERS.get(learner.lower(), learner)
    with database.transaction() as db:
        if db.get(LearnerRow, learner_id) is None:
            raise SystemExit(f"Unknown learner: {learner}")
    return learner_id


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def cmd_migrate(args: argparse.Namespace) -> int:
    _print({"database_revision": upgrade_to_head(args.database_url)})
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            inserted = seed_database(db)
        with database.transaction() as db:
            counts = {
                table.name: db.execute(select(func.count()).select_from(table)).scalar_one()
                for table in Base.metadata.sorted_tables
            }
    finally:
        database.dispose()
    _print({"seed_version": SEED_VERSION, "inserted": inserted, "row_counts": counts})
    return 0


def cmd_learners(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            rows = db.execute(select(LearnerRow).order_by(LearnerRow.created_at)).scalars()
            learners = [
                {
                    "id": row.id,
                    "display_name": row.display_name,
                    "is_fictional": row.is_fictional,
                    "provenance": row.provenance,
                }
                for row in rows
            ]
    finally:
        database.dispose()
    _print({"learners": learners, "aliases": DEMO_LEARNERS})
    return 0


def cmd_pair(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        learner_id = _resolve_learner(database, args.learner)
        now = utc_now()
        ttl = timedelta(seconds=args.ttl_seconds)
        try:
            with database.transaction() as db:
                code = issue_pairing_code(db, learner_id, now, ttl)
        except PairingError as error:
            raise SystemExit(str(error)) from error
    finally:
        database.dispose()
    _print(
        {
            "learner_id": learner_id,
            "pairing_code": code,
            "expires_at": (now + ttl).isoformat(),
            "note": "One-time code. Redeem with POST /pairing/redeem on the private local API.",
        }
    )
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        learner_id = _resolve_learner(database, args.learner)
        with database.transaction() as db:
            revoked = revoke_all_for_learner(db, learner_id, utc_now())
    finally:
        database.dispose()
    _print({"learner_id": learner_id, "revoked_credentials": revoked})
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        learner_id = _resolve_learner(database, args.learner)
        with database.transaction() as db:
            # Administrative read: the scope is chosen by the local operator, not a credential.
            repo = ScopedRepository(db, LearnerScope(learner_id=learner_id, credential_id="cli"))
            snapshot = repo.history(args.limit)
    finally:
        database.dispose()
    print(snapshot.model_dump_json(indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL (default: DATABASE_URL or sqlite:///./data/tutor.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Apply Alembic migrations up to head").set_defaults(
        handler=cmd_migrate
    )
    sub.add_parser("seed", help="Insert missing fictional seed records").set_defaults(
        handler=cmd_seed
    )
    sub.add_parser("learners", help="List learners and their fictional labels").set_defaults(
        handler=cmd_learners
    )
    pair = sub.add_parser("pair", help="Issue a one-time pairing code for a learner")
    pair.add_argument("--learner", required=True, help="Learner ID or seed alias (ada, ben)")
    pair.add_argument("--ttl-seconds", type=int, default=None)
    pair.set_defaults(handler=cmd_pair)
    revoke = sub.add_parser("revoke", help="Revoke every credential of a learner")
    revoke.add_argument("--learner", required=True)
    revoke.set_defaults(handler=cmd_revoke)
    history = sub.add_parser("history", help="Print a learner's recent records with provenance")
    history.add_argument("--learner", required=True)
    history.add_argument("--limit", type=int, default=20, choices=range(1, MAX_HISTORY_ITEMS + 1))
    history.set_defaults(handler=cmd_history)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.database_url is None:
        args.database_url = settings.database_url
    if getattr(args, "ttl_seconds", 0) is None:
        args.ttl_seconds = settings.pairing_code_ttl_seconds
    result: int = args.handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
