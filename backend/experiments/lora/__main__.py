"""Train, reload or evaluate the tiny random-base LoRA smoke.

From the repository root, after preparing reviewed examples:

    PYTHONPATH=backend backend/.venv/bin/python -m experiments.lora train \\
        --smoke --seed 17 --steps 2 --data artifacts/tutor-data --output artifacts/lora-smoke
    PYTHONPATH=backend backend/.venv/bin/python -m experiments.lora reload \\
        --checkpoint artifacts/lora-smoke
    PYTHONPATH=backend backend/.venv/bin/python -m experiments.lora evaluate \\
        --checkpoint artifacts/lora-smoke --data artifacts/tutor-data
"""

import argparse
import json
from pathlib import Path

from experiments.lora.model import PretrainedLoRADisabledError, build_random_base
from experiments.lora.train import evaluate_lora, reload_checkpoint, train_smoke
from experiments.tutor_data.contracts import SharedExample


def _count(value: object) -> int | None:
    if isinstance(value, list):
        return len(value)
    return None


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_examples(path: Path) -> list[SharedExample]:
    examples: list[SharedExample] = []
    for line in path.read_text().splitlines():
        if line.strip():
            examples.append(SharedExample.model_validate_json(line))
    return examples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.lora", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train", help="Train a tiny random-base LoRA adapter")
    train.add_argument("--smoke", action="store_true", required=True)
    train.add_argument("--seed", type=int, required=True)
    train.add_argument("--steps", type=int, default=2)
    train.add_argument("--data", type=Path, required=True, help="Directory containing train.jsonl")
    train.add_argument("--output", type=Path, required=True)
    train.add_argument(
        "--pretrained",
        action="store_true",
        help="Select the opt-in pretrained config. Downloads stay disabled.",
    )
    reload = commands.add_parser("reload", help="Reload the adapter on the saved random base")
    reload.add_argument("--checkpoint", type=Path, required=True)
    evaluate = commands.add_parser("evaluate", help="Compare base and adapter on held-out prompts")
    evaluate.add_argument("--checkpoint", type=Path, required=True)
    evaluate.add_argument(
        "--data", type=Path, required=True, help="Directory containing heldout.jsonl"
    )
    args = parser.parse_args(argv)
    if args.command == "train" and args.pretrained:
        try:
            build_random_base(seed=args.seed, pretrained=True, allow_download=False)
        except PretrainedLoRADisabledError as error:
            _print({"pretrained_activated": False, "error": str(error)})
            return 2
    if args.command == "train":
        examples = _load_examples(args.data / "train.jsonl")
        report = train_smoke(args.output, examples, seed=args.seed, steps=args.steps)
        _print(
            {
                "execution_status": report["execution_status"],
                "adapter_l1_delta": report["adapter_l1_delta"],
                "base_max_abs_delta": report["base_max_abs_delta"],
                "reload": report["reload"],
                "pretrained_activated": report["pretrained_activated"],
                "output": str(args.output),
            }
        )
        return 0
    if args.command == "reload":
        _print(reload_checkpoint(args.checkpoint))
        return 0
    report = evaluate_lora(args.checkpoint, _load_examples(args.data / "heldout.jsonl"))
    destination = args.checkpoint / "evaluation.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    _print(
        {
            "output": str(destination),
            "improvements": _count(report.get("improvements")),
            "regressions": _count(report.get("regressions")),
            "limitations": report["limitations"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
