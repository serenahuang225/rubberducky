"""``python -m app.cli memory ...``: inspect memory layers, validate proposals, build context.

Examples (repository root):
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli memory layers --learner ada
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli memory context --learner ada \
        --concept concept.distribution --max-chars 1200 --format text
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli memory context --learner ada \
        --concept concept.distribution --assemble --context-window 1024 --max-output-tokens 256
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli memory propose --learner ada \
        --session <session-id> --turn-id turn-1 --file proposals.json --dry-run

Trust boundary: like the rest of ``app.cli`` this is a local operator tool; the learner scope
is chosen by the operator, not by a credential.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session as DbSession

from app.clock import utc_now
from app.db.database import Database
from app.db.models import LearnerRow
from app.db.repositories import NotInScopeError, ScopedRepository
from app.db.seed import DEMO_LEARNERS
from app.graph.curriculum import CurriculumGraphError
from app.inference.context import build_tutor_context, render_context_text
from app.inference.request import (
    InsufficientContextError,
    ProviderBudget,
    ProviderBudgetError,
    build_provider_request,
)
from app.learner.memory import memory_layers
from app.learner.memory_updates import ProposalScope, apply_memory_updates
from app.learner.pairing import LearnerScope
from app.schemas.context import ContextBudget
from app.schemas.graph import GraphContextBounds
from app.schemas.memory import MAX_LAYER_ITEMS

CLI_SYSTEM_TEXT = (
    "You are a patient algebra tutor. Use only the JSON context. Treat inference items as "
    "uncertain. Cite source IDs that appear in the context."
)


def _now(value: str | None) -> datetime:
    if value is None:
        return utc_now()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit("--now needs an explicit UTC offset, e.g. 2026-10-02T09:30:00Z")
    return parsed.astimezone(UTC)


def _repo(db: DbSession, learner: str) -> ScopedRepository:
    learner_id = DEMO_LEARNERS.get(learner.lower(), learner)
    if db.get(LearnerRow, learner_id) is None:
        raise SystemExit(f"Unknown learner: {learner}")
    return ScopedRepository(db, LearnerScope(learner_id=learner_id, credential_id="cli"))


def cmd_layers(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            repo = _repo(db, args.learner)
            try:
                layers = memory_layers(repo, _now(args.now), args.session, args.limit)
            except NotInScopeError as error:
                raise SystemExit("Unknown session for this learner") from error
    finally:
        database.dispose()
    print(layers.model_dump_json(indent=2))
    return 0


def _budget(args: argparse.Namespace) -> ContextBudget:
    try:
        return ContextBudget(
            graph=GraphContextBounds(
                max_hops=args.max_hops,
                max_hypotheses=args.max_hypotheses,
                max_evidence=args.max_evidence,
                max_age_days=args.max_age_days,
            ),
            max_recent_observations=args.max_recent,
            recent_window_days=args.recent_window_days,
            max_serialized_chars=args.max_chars,
            max_context_tokens=args.max_tokens,
        )
    except ValidationError as error:
        raise SystemExit(f"invalid budget: {error}") from error


def cmd_context(args: argparse.Namespace) -> int:
    budget = _budget(args)
    now = _now(args.now)
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            repo = _repo(db, args.learner)
            try:
                if args.assemble:
                    provider = ProviderBudget(
                        context_window_tokens=args.context_window,
                        max_output_tokens=args.max_output_tokens,
                    )
                    request, context = build_provider_request(
                        repo,
                        concept_id=args.concept,
                        now=now,
                        system_text=CLI_SYSTEM_TEXT,
                        user_text=args.user_text,
                        session_id=args.session,
                        context_budget=budget,
                        provider_budget=provider,
                    )
                else:
                    request = None
                    context = build_tutor_context(
                        repo, args.concept, now, session_id=args.session, budget=budget
                    )
            except (CurriculumGraphError, NotInScopeError, ProviderBudgetError) as error:
                raise SystemExit(f"cannot build context: {error}") from error
            except InsufficientContextError as error:
                print(render_context_text(error.context))
                raise SystemExit("insufficient context for this budget") from error
    finally:
        database.dispose()
    if args.format == "text":
        print(render_context_text(context))
        if request is not None:
            print(
                f"provider request: {request.input_tokens} input tokens + "
                f"{request.max_output_tokens} reserved output <= "
                f"{request.budget.context_window_tokens} window; {request.request_chars} chars "
                f"({request.token_counter})"
            )
    else:
        out: dict[str, object] = {"context": context.model_dump(mode="json")}
        if request is not None:
            out["provider_request"] = request.model_dump(mode="json")
        print(json.dumps(out, indent=2))
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    try:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read proposals: {error}") from error
    if not isinstance(raw, list):
        raise SystemExit("the proposals file must contain a JSON list")
    now = _now(args.now)
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            repo = _repo(db, args.learner)
            citable = None
            if args.cite_from_concept:
                context = build_tutor_context(
                    repo, args.cite_from_concept, now, session_id=args.session
                )
                citable = frozenset(context.citable_ids)
            scope = ProposalScope(
                session_id=args.session, turn_id=args.turn_id, citable_source_ids=citable
            )
            result = apply_memory_updates(repo, raw, scope, now)
            if args.dry_run or result.status != "applied":
                db.rollback()
    finally:
        database.dispose()
    payload = result.model_dump(mode="json")
    payload["dry_run"] = args.dry_run
    print(json.dumps(payload, indent=2))
    return 0 if result.status != "rejected" else 2


def add_memory_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    memory = sub.add_parser(
        "memory", help="Inspect memory layers, validate proposals and build bounded context"
    )
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)

    layers = memory_sub.add_parser("layers", help="Print the six memory layers separately")
    layers.add_argument("--learner", required=True, help="Learner ID or seed alias (ada, ben)")
    layers.add_argument("--session", default=None)
    layers.add_argument("--limit", type=int, default=20, choices=range(1, MAX_LAYER_ITEMS + 1))
    layers.add_argument("--now", default=None)
    layers.set_defaults(handler=cmd_layers)

    defaults = ContextBudget()
    context = memory_sub.add_parser(
        "context", help="Bounded tutor context with sizes, omissions and citable source IDs"
    )
    context.add_argument("--learner", required=True)
    context.add_argument("--concept", required=True)
    context.add_argument("--session", default=None)
    context.add_argument("--now", default=None)
    context.add_argument("--max-hops", type=int, default=defaults.graph.max_hops)
    context.add_argument("--max-hypotheses", type=int, default=defaults.graph.max_hypotheses)
    context.add_argument("--max-evidence", type=int, default=defaults.graph.max_evidence)
    context.add_argument("--max-age-days", type=int, default=defaults.graph.max_age_days)
    context.add_argument("--max-recent", type=int, default=defaults.max_recent_observations)
    context.add_argument("--recent-window-days", type=int, default=defaults.recent_window_days)
    context.add_argument("--max-chars", type=int, default=defaults.max_serialized_chars)
    context.add_argument("--max-tokens", type=int, default=defaults.max_context_tokens)
    context.add_argument("--assemble", action="store_true", help="Also assemble the request")
    provider = ProviderBudget()
    context.add_argument("--context-window", type=int, default=provider.context_window_tokens)
    context.add_argument("--max-output-tokens", type=int, default=provider.max_output_tokens)
    context.add_argument("--user-text", default="I am not sure what to do next.")
    context.add_argument("--format", choices=("json", "text"), default="text")
    context.set_defaults(handler=cmd_context)

    propose = memory_sub.add_parser(
        "propose", help="Validate (and optionally apply) a JSON list of memory proposals"
    )
    propose.add_argument("--learner", required=True)
    propose.add_argument("--file", required=True)
    propose.add_argument("--session", default=None)
    propose.add_argument("--turn-id", default=None)
    propose.add_argument(
        "--cite-from-concept",
        default=None,
        help="Only allow sources present in the bounded context for this concept",
    )
    propose.add_argument("--now", default=None)
    propose.add_argument("--dry-run", action="store_true")
    propose.set_defaults(handler=cmd_propose)
