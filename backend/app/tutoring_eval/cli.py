"""``python -m app.cli evaluation ...``: replay tutoring cases, score them, optionally use Chalk.

Everything is local and read-only except ``chalk-run --confirm-live``, which is refused
unless Chalk evaluation is explicitly enabled and fully configured, and which then uploads a
small fictional dataset, deploys scorer functions and runs an evaluation in your Chalk
environment (this can cost money and has not been verified live).

Examples (from ``backend/``, with ``python`` = ``.venv/bin/python``):
    python -m app.cli evaluation status
    python -m app.cli evaluation cases
    python -m app.cli evaluation run --candidate fixture:good
    python -m app.cli evaluation run --responses-file replies.jsonl
    python -m app.cli evaluation chalk-plan --candidate fixture:good
    python -m app.cli evaluation chalk-run --candidate fixture:good --confirm-live
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.redaction import redact_text
from app.tutoring_eval.candidates import (
    FIXTURE_CANDIDATES,
    Candidate,
    CandidateError,
    fixture_candidate,
    responses_file_candidate,
)
from app.tutoring_eval.cases import CASE_SET_VERSION, build_fixture_cases
from app.tutoring_eval.chalk_adapter import (
    ChalkEvaluationAdapter,
    ChalkNotActivatedError,
    build_dataset_rows,
    describe_chalk_evaluation,
)
from app.tutoring_eval.contracts import (
    DEFAULT_MAX_HISTORY,
    MAX_HISTORY_LIMIT,
    EvaluationReport,
    ReplaySnapshot,
)
from app.tutoring_eval.replay import build_snapshots
from app.tutoring_eval.runner import DEFAULT_LATENCY_BUDGET_MS, evaluate_candidate


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _candidate(args: argparse.Namespace) -> Candidate:
    if args.responses_file:
        return responses_file_candidate(Path(args.responses_file))
    name = args.candidate.removeprefix("fixture:")
    return fixture_candidate(name)


def _replay(args: argparse.Namespace) -> tuple[list[ReplaySnapshot], EvaluationReport]:
    snapshots = build_snapshots(build_fixture_cases(), args.max_history)
    report = evaluate_candidate(
        _candidate(args), snapshots, latency_budget_ms=args.latency_budget_ms
    )
    return snapshots, report


def cmd_status(_args: argparse.Namespace) -> int:
    _print(describe_chalk_evaluation(get_settings()).model_dump(mode="json"))
    return 0


def cmd_cases(args: argparse.Namespace) -> int:
    cases = build_fixture_cases()
    snapshots = build_snapshots(cases, args.max_history)
    _print(
        {
            "case_set_version": CASE_SET_VERSION,
            "is_fictional": True,
            "turns": [
                {
                    "case_id": s.case_id,
                    "turn_id": s.turn_id,
                    "scenario": s.scenario,
                    "cutoff": s.cutoff.isoformat(),
                    "visible_source_ids": s.available_source_ids,
                    "omitted_future_events": s.omitted_future_events,
                    "omitted_by_bound": s.omitted_by_bound,
                    "digest": s.digest,
                }
                for s in snapshots
            ],
        }
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        _, report = _replay(args)
    except (CandidateError, ValueError, OSError) as error:
        _print({"error": redact_text(str(error))[:200]})
        return 1
    _print(report.model_dump(mode="json"))
    return 0 if report.errors == 0 else 1


def cmd_chalk_plan(args: argparse.Namespace) -> int:
    try:
        snapshots, report = _replay(args)
    except (CandidateError, ValueError, OSError) as error:
        _print({"error": redact_text(str(error))[:200]})
        return 1
    _, plan = build_dataset_rows(snapshots, report)
    _print(
        {
            "status": describe_chalk_evaluation(get_settings()).model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "note": "Computed locally. Nothing was uploaded, deployed or run.",
        }
    )
    return 0


def cmd_chalk_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not args.confirm_live:
        _print(
            {
                "refused": "this uploads data, deploys functions and runs a paid Chalk evaluation",
                "next": "re-run with --confirm-live after enabling and configuring Chalk",
                "status": describe_chalk_evaluation(settings).model_dump(mode="json"),
            }
        )
        return 2
    try:
        snapshots, report = _replay(args)
    except (CandidateError, ValueError, OSError) as error:
        _print({"error": redact_text(str(error))[:200]})
        return 1
    adapter = ChalkEvaluationAdapter(settings)
    try:
        result = adapter.run(
            snapshots,
            report,
            evaluation_name=args.name,
            include_judge=args.include_judge,
        )
    except ChalkNotActivatedError as error:
        _print({"refused": redact_text(str(error))[:300]})
        return 2
    except Exception as error:
        _print(
            {
                "error": f"{type(error).__name__}: {redact_text(str(error))[:300]}",
                "requests_sent": [r.step for r in adapter.requests],
            }
        )
        return 1
    _print(result.model_dump(mode="json"))
    return 0 if result.usable else 1


def _add_replay_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--candidate",
        choices=[f"fixture:{name}" for name in sorted(FIXTURE_CANDIDATES)],
        default="fixture:good",
        help="Scripted fixture candidate (labeled fixture; not a model)",
    )
    source.add_argument(
        "--responses-file",
        help="JSONL of precomputed replies: case_id, turn_id, text[, cited_source_ids, "
        "answer_revealed, latency_ms]",
    )
    parser.add_argument(
        "--max-history", type=int, default=DEFAULT_MAX_HISTORY, choices=range(MAX_HISTORY_LIMIT + 1)
    )
    parser.add_argument("--latency-budget-ms", type=float, default=DEFAULT_LATENCY_BUDGET_MS)


def add_evaluation_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    root = sub.add_parser(
        "evaluation", help="History-grounded tutoring evaluation and the optional Chalk adapter"
    )
    commands = root.add_subparsers(dest="evaluation_command", required=True)
    commands.add_parser(
        "status", help="Chalk evaluation activation status (no network)"
    ).set_defaults(handler=cmd_status)
    cases = commands.add_parser("cases", help="Replay cutoffs and visible source IDs per turn")
    cases.add_argument(
        "--max-history", type=int, default=DEFAULT_MAX_HISTORY, choices=range(MAX_HISTORY_LIMIT + 1)
    )
    cases.set_defaults(handler=cmd_cases)
    run = commands.add_parser("run", help="Score a candidate locally with the deterministic rubric")
    _add_replay_arguments(run)
    run.set_defaults(handler=cmd_run)
    plan = commands.add_parser("chalk-plan", help="Show the dataset a Chalk run would upload")
    _add_replay_arguments(plan)
    plan.set_defaults(handler=cmd_chalk_plan)
    live = commands.add_parser(
        "chalk-run", help="Upload, evaluate and read back in Chalk (explicit, paid, unverified)"
    )
    _add_replay_arguments(live)
    live.add_argument("--name", default="rubberducky-tutoring-replay-eval")
    live.add_argument("--include-judge", action="store_true", help="Also run the model judge")
    live.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required: allow contacting Chalk (never needed for status, cases, run, chalk-plan)",
    )
    live.set_defaults(handler=cmd_chalk_run)


if __name__ == "__main__":
    sys.exit("run through: python -m app.cli evaluation")
