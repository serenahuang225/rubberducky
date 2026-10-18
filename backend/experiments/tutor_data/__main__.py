"""Validate, prepare or dry-run shared tutor examples, or gate teacher generation.

From the repository root:

    PYTHONPATH=backend backend/.venv/bin/python -m experiments.tutor_data validate \\
        --input backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl
    PYTHONPATH=backend backend/.venv/bin/python -m experiments.tutor_data prepare \\
        --input backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl \\
        --output artifacts/tutor-data --seed 17
    PYTHONPATH=backend backend/.venv/bin/python -m experiments.tutor_data dry-run \\
        --input backend/experiments/tutor_data/fixtures/reviewed_shared.jsonl \\
        --output artifacts/tutor-data-dry --seed 17
    PYTHONPATH=backend backend/.venv/bin/python -m experiments.tutor_data teacher \\
        --output artifacts/teacher-mock --activate --provider mock --max-cost-usd 0.05
"""

import argparse
import json
from pathlib import Path

from experiments.tutor_data.prepare import prepare_examples, validate_examples
from experiments.tutor_data.teacher import (
    MockTeacherTransport,
    TeacherBudgetError,
    TeacherGenerationDisabledError,
    generate_teacher_examples,
)

DEFAULT_PROMPT = (
    "Learner wrote 2x+3=14 for 2(x+3)=14. Ask about both terms. Do not state x=4."
)


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.tutor_data", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Accept or reject rows without writing a split")
    validate.add_argument("--input", type=Path, required=True)
    prepare = commands.add_parser(
        "prepare", help="Write a family-separated train/held-out manifest"
    )
    dry_run = commands.add_parser("dry-run", help="Write the manifest only, no training rows")
    for command in (prepare, dry_run):
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--seed", type=int, required=True)
        command.add_argument("--heldout-fraction", type=float, default=0.34)
    teacher = commands.add_parser(
        "teacher", help="Generate examples only when explicitly activated"
    )
    teacher.add_argument("--output", type=Path, required=True)
    teacher.add_argument("--activate", action="store_true")
    teacher.add_argument("--provider", default="mock")
    teacher.add_argument("--max-cost-usd", type=float, default=None)
    teacher.add_argument("--max-examples", type=int, default=1)
    teacher.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "validate":
        report = validate_examples(args.input)
        _print(
            {
                "accepted_ids": report.accepted_ids,
                "excluded": [
                    {"example_id": item.example_id, "reason": item.reason}
                    for item in report.excluded
                ],
                "download_count": report.download_count,
            }
        )
        return 0
    if args.command in {"prepare", "dry-run"}:
        prepared = prepare_examples(
            args.input,
            seed=args.seed,
            heldout_fraction=args.heldout_fraction,
            output_dir=args.output,
            dry_run=args.command == "dry-run",
        )
        _print(
            {
                "dry_run": prepared.dry_run,
                "train_ids": prepared.train_ids,
                "heldout_ids": prepared.heldout_ids,
                "excluded": [
                    {"example_id": item.example_id, "reason": item.reason}
                    for item in prepared.excluded
                ],
                "download_count": prepared.download_count,
                "output": str(args.output),
            }
        )
        return 0
    prompts = [DEFAULT_PROMPT][: args.max_examples]
    try:
        generated = generate_teacher_examples(
            prompts,
            transport=MockTeacherTransport(),
            activated=args.activate,
            max_cost_usd=args.max_cost_usd,
            provider=args.provider,
            allow_remote=args.allow_remote,
        )
    except (TeacherGenerationDisabledError, TeacherBudgetError) as error:
        _print({"activated": False, "error": str(error), "download_count": 0})
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    lines = [example.model_dump_json() for example in generated]
    (args.output / "unreviewed.jsonl").write_text("\n".join(lines) + "\n")
    _print(
        {
            "activated": True,
            "review_status": "unreviewed",
            "count": len(generated),
            "output": str(args.output / "unreviewed.jsonl"),
            "note": "Unreviewed generations are not training data.",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
