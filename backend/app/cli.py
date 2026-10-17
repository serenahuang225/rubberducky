"""Local administrative CLI: migrate, seed, pair, revoke, inspect history and graph context.

Trust boundary: this CLI reads and writes the database file directly with no credential
checks. Anyone able to run it can already read the file, so it is a local operator tool and
is never exposed over HTTP. Pairing codes it prints are one-time and short-lived; bearer
tokens are never printed.

Run from the repository root:
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli migrate
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli graph context --learner ada \
        --concept concept.distribution --format text
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import func, select

from app.clock import utc_now
from app.config import get_settings
from app.db.database import Database
from app.db.migrate import upgrade_to_head
from app.db.models import Base, LearnerRow
from app.db.repositories import MAX_HISTORY_ITEMS, ScopedRepository
from app.db.seed import DEMO_LEARNERS, SEED_VERSION, seed_database
from app.graph.context import build_graph_context, render_text
from app.graph.curriculum import (
    CurriculumGraph,
    CurriculumGraphError,
    add_prerequisite_edge,
    load_curriculum_graph,
    validation_report,
)
from app.learner.pairing import (
    LearnerScope,
    PairingError,
    issue_pairing_code,
    revoke_all_for_learner,
)
from app.schemas.graph import MAX_CONTEXT_HOPS, GraphContextBounds


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


def _graph_report(args: argparse.Namespace, build: Callable[[CurriculumGraph], object]) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            try:
                payload = build(load_curriculum_graph(db))
            except CurriculumGraphError as error:
                raise SystemExit(str(error)) from error
    finally:
        database.dispose()
    _print(payload)
    return 0


def cmd_graph_validate(args: argparse.Namespace) -> int:
    return _graph_report(args, validation_report)


def cmd_graph_prerequisites(args: argparse.Namespace) -> int:
    def build(graph: CurriculumGraph) -> object:
        return {
            "concept_id": args.concept,
            "max_hops": args.max_hops,
            "direct_prerequisites": graph.direct_prerequisites(args.concept),
            "prerequisites": graph.prerequisites(args.concept, args.max_hops),
            "dependents": graph.dependents(args.concept, args.max_hops),
        }

    return _graph_report(args, build)


def cmd_graph_neighborhood(args: argparse.Namespace) -> int:
    return _graph_report(
        args,
        lambda graph: {
            "concept_id": args.concept,
            "max_hops": args.max_hops,
            "neighborhood": graph.neighborhood(args.concept, args.max_hops),
        },
    )


def cmd_graph_add_edge(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            try:
                edge = add_prerequisite_edge(db, args.prerequisite, args.concept, utc_now())
            except CurriculumGraphError as error:
                raise SystemExit(str(error)) from error
            if args.dry_run:
                db.rollback()
    finally:
        database.dispose()
    _print({"dry_run": args.dry_run, "edge": edge.model_dump(mode="json")})
    return 0


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return utc_now()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit("--now needs an explicit UTC offset, e.g. 2026-10-02T09:30:00Z")
    return parsed.astimezone(UTC)


def cmd_graph_context(args: argparse.Namespace) -> int:
    try:
        bounds = GraphContextBounds(
            max_hops=args.max_hops,
            max_nodes=args.max_nodes,
            max_hypotheses=args.max_hypotheses,
            max_evidence=args.max_evidence,
            max_age_days=args.max_age_days,
        )
    except ValidationError as error:
        raise SystemExit(f"invalid bounds: {error}") from error
    database = Database(args.database_url)
    try:
        learner_id = _resolve_learner(database, args.learner)
        with database.transaction() as db:
            # Administrative read: the scope is chosen by the local operator, not a credential.
            repo = ScopedRepository(db, LearnerScope(learner_id=learner_id, credential_id="cli"))
            try:
                context = build_graph_context(repo, args.concept, _parse_now(args.now), bounds)
            except CurriculumGraphError as error:
                raise SystemExit(str(error)) from error
    finally:
        database.dispose()
    print(render_text(context) if args.format == "text" else context.model_dump_json(indent=2))
    return 0


def _add_graph_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    graph = sub.add_parser(
        "graph", help="Inspect the curated prerequisite DAG and bounded learner graph context"
    )
    graph_sub = graph.add_subparsers(dest="graph_command", required=True)
    graph_sub.add_parser("validate", help="Check the persisted curriculum is a DAG").set_defaults(
        handler=cmd_graph_validate
    )
    hop_choices = range(MAX_CONTEXT_HOPS + 1)
    prerequisites = graph_sub.add_parser("prerequisites", help="Prerequisites and dependents")
    prerequisites.add_argument("--concept", required=True)
    prerequisites.add_argument("--max-hops", type=int, default=None, choices=hop_choices)
    prerequisites.set_defaults(handler=cmd_graph_prerequisites)
    neighborhood = graph_sub.add_parser("neighborhood", help="Concepts within N hops")
    neighborhood.add_argument("--concept", required=True)
    neighborhood.add_argument("--max-hops", type=int, default=1, choices=hop_choices)
    neighborhood.set_defaults(handler=cmd_graph_neighborhood)
    add_edge = graph_sub.add_parser("add-edge", help="Add a curated edge; cycles are rejected")
    add_edge.add_argument("--prerequisite", required=True)
    add_edge.add_argument("--concept", required=True)
    add_edge.add_argument("--dry-run", action="store_true", help="Validate without saving")
    add_edge.set_defaults(handler=cmd_graph_add_edge)
    context = graph_sub.add_parser(
        "context", help="Bounded context: neighborhood plus support/contradiction evidence"
    )
    context.add_argument("--learner", required=True, help="Learner ID or seed alias (ada, ben)")
    context.add_argument("--concept", required=True)
    defaults = GraphContextBounds()
    context.add_argument("--max-hops", type=int, default=defaults.max_hops)
    context.add_argument("--max-nodes", type=int, default=defaults.max_nodes)
    context.add_argument("--max-hypotheses", type=int, default=defaults.max_hypotheses)
    context.add_argument("--max-evidence", type=int, default=defaults.max_evidence)
    context.add_argument("--max-age-days", type=int, default=None)
    context.add_argument("--now", default=None, help="ISO-8601 time with offset (default: now)")
    context.add_argument("--format", choices=("json", "text"), default="json")
    context.set_defaults(handler=cmd_graph_context)

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
    _add_graph_parser(sub)
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
