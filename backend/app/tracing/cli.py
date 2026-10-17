"""``python -m app.cli tracing ...``: inspect, replay and version BKT tracing locally.

Examples (repository root):
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli tracing fixture
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli tracing replay --learner bkt-fixture
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli tracing parameters add \
        --parameter-version bkt-handset-no-learn.v1 --p-init 0.2 --p-learn 0 \
        --p-guess 0.25 --p-slip 0.1 --description "No-learning comparison"
    PYTHONPATH=backend backend/.venv/bin/python -m app.cli tracing replay \
        --learner bkt-fixture --parameter-version bkt-handset-no-learn.v1
"""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.clock import utc_now
from app.db.database import Database
from app.db.models import LearnerRow
from app.db.seed import DEMO_LEARNERS, curriculum_records, insert_missing
from app.tracing.contracts import DEFAULT_PARAMETERS, BKTParameters, ReplayReport
from app.tracing.fixtures import FIXTURE_ALIAS, FIXTURE_LEARNER_ID, bkt_fixture_records
from app.tracing.presentation import readiness_report
from app.tracing.replay import (
    ParameterConflictError,
    UnknownParameterVersionError,
    list_parameters,
    load_events,
    persisted_tracing,
    register_parameters,
    replay_events,
    replay_learner,
)

ALIASES = {**DEMO_LEARNERS, FIXTURE_ALIAS: FIXTURE_LEARNER_ID}


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _learner_id(database: Database, learner: str) -> str:
    learner_id = ALIASES.get(learner.lower(), learner)
    with database.transaction() as db:
        if db.get(LearnerRow, learner_id) is None:
            raise SystemExit(f"Unknown learner: {learner}")
    return learner_id


def render_report_text(report: ReplayReport, persisted: bool) -> str:
    p = report.parameters
    lines = [
        f"learner {report.learner_id}",
        f"algorithm {report.metadata.algorithm} {report.metadata.algorithm_version}; "
        f"eligibility {report.metadata.eligibility_version}",
        f"parameters {p.parameter_version} ({p.source}, calibrated={p.calibrated}): "
        f"p_init={p.p_init} p_learn={p.p_learn} p_guess={p.p_guess} p_slip={p.p_slip}",
        f"raw events {len(report.raw_event_ids)}; counted opportunities "
        f"{report.counted_opportunities}; persisted={persisted}",
    ]
    for update in report.updates:
        line = f"  {update.observation_id} {update.status}"
        if update.reason:
            line += f" ({update.reason})"
        if update.prediction is not None:
            line += (
                f" p_known_before={update.prediction.latent_knowledge:.12f}"
                f" p_correct_predicted={update.prediction.p_correct:.12f}"
                f" observed_correct={update.observed_correct}"
            )
        if update.p_known_after is not None and update.p_known_posterior is not None:
            line += (
                f" p_known_posterior={update.p_known_posterior:.12f}"
                f" p_known_after={update.p_known_after:.12f}"
            )
        lines.append(line)
    for estimate in report.estimates:
        lines.append(
            f"estimate {estimate.concept_id}: p_known={estimate.p_known:.12f} after "
            f"{estimate.counted_opportunities} counted opportunities"
        )
    lines.append(report.note)
    return "\n".join(lines)


def cmd_fixture(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            inserted = insert_missing(db, [*curriculum_records(), *bkt_fixture_records()])
    finally:
        database.dispose()
    _print({"learner_id": FIXTURE_LEARNER_ID, "alias": FIXTURE_ALIAS, "inserted": inserted})
    return 0


def cmd_parameters_list(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            stored = [p.model_dump(mode="json") for p in list_parameters(db)]
    finally:
        database.dispose()
    _print({"default": DEFAULT_PARAMETERS.model_dump(mode="json"), "stored": stored})
    return 0


def cmd_parameters_add(args: argparse.Namespace) -> int:
    try:
        parameters = BKTParameters(
            parameter_version=args.parameter_version,
            p_init=args.p_init,
            p_learn=args.p_learn,
            p_guess=args.p_guess,
            p_slip=args.p_slip,
            source="hand_set",
            calibrated=False,
            description=args.description,
        )
    except ValidationError as error:
        raise SystemExit(f"invalid parameters: {error}") from error
    database = Database(args.database_url)
    try:
        with database.transaction() as db:
            try:
                inserted = register_parameters(db, parameters, utc_now())
            except ParameterConflictError as error:
                raise SystemExit(str(error)) from error
    finally:
        database.dispose()
    _print({"inserted": inserted, "parameters": parameters.model_dump(mode="json")})
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        learner_id = _learner_id(database, args.learner)
        with database.transaction() as db:
            try:
                predictor, report = replay_learner(
                    db, learner_id, utc_now(), args.parameter_version, persist=not args.dry_run
                )
            except UnknownParameterVersionError as error:
                raise SystemExit(f"Unknown parameter version: {error}") from error
    finally:
        database.dispose()
    if args.state_out is not None:
        Path(args.state_out).write_text(predictor.save().model_dump_json(indent=2) + "\n")
    if args.format == "text":
        print(render_report_text(report, persisted=not args.dry_run))
    else:
        payload = report.model_dump(mode="json")
        payload["persisted"] = not args.dry_run
        _print(payload)
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        learner_id = _learner_id(database, args.learner)
        with database.transaction() as db:
            state = persisted_tracing(db, learner_id, args.parameter_version)
    finally:
        database.dispose()
    print(state.model_dump_json(indent=2))
    return 0


def cmd_readiness(args: argparse.Namespace) -> int:
    database = Database(args.database_url)
    try:
        learner_id = _learner_id(database, args.learner)
        with database.transaction() as db:
            events = load_events(db, learner_id)
    finally:
        database.dispose()
    predictor, _ = replay_events(learner_id, events, DEFAULT_PARAMETERS)
    print(readiness_report(events, predictor).model_dump_json(indent=2))
    return 0


def add_tracing_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    tracing = sub.add_parser("tracing", help="BKT replay, parameter versions and readiness")
    tracing_sub = tracing.add_subparsers(dest="tracing_command", required=True)
    tracing_sub.add_parser(
        "fixture", help=f"Insert the fictional '{FIXTURE_ALIAS}' replay learner (idempotent)"
    ).set_defaults(handler=cmd_fixture)

    parameters = tracing_sub.add_parser("parameters", help="List or add BKT parameter versions")
    parameters_sub = parameters.add_subparsers(dest="parameters_command", required=True)
    parameters_sub.add_parser("list", help="Show stored parameter sets").set_defaults(
        handler=cmd_parameters_list
    )
    add = parameters_sub.add_parser("add", help="Register a new immutable hand-set version")
    add.add_argument("--parameter-version", required=True)
    for name in ("p-init", "p-learn", "p-guess", "p-slip"):
        add.add_argument(f"--{name}", type=float, required=True)
    add.add_argument("--description", required=True)
    add.set_defaults(handler=cmd_parameters_add)

    learner_help = f"Learner ID or alias ({', '.join(sorted(ALIASES))})"
    replay = tracing_sub.add_parser(
        "replay", help="Recompute estimates from raw evidence and replace derived rows"
    )
    replay.add_argument("--learner", required=True, help=learner_help)
    replay.add_argument("--parameter-version", default=DEFAULT_PARAMETERS.parameter_version)
    replay.add_argument("--dry-run", action="store_true", help="Compute without persisting")
    replay.add_argument("--state-out", default=None, help="Write the predictor snapshot JSON")
    replay.add_argument("--format", choices=("json", "text"), default="json")
    replay.set_defaults(handler=cmd_replay)

    state = tracing_sub.add_parser("state", help="Show persisted counted opportunities/estimates")
    state.add_argument("--learner", required=True, help=learner_help)
    state.add_argument("--parameter-version", default=DEFAULT_PARAMETERS.parameter_version)
    state.set_defaults(handler=cmd_state)

    readiness = tracing_sub.add_parser("readiness", help="Learner-facing qualitative projection")
    readiness.add_argument("--learner", required=True, help=learner_help)
    readiness.set_defaults(handler=cmd_readiness)
