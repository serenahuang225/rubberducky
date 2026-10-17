"""Train or evaluate the synthetic causal GRU.

From the repository root:

    PYTHONPATH=backend backend/.venv/bin/python -m experiments.tracing train \\
        --synthetic --seed 17 --epochs 2 --output artifacts/gru-smoke
    PYTHONPATH=backend backend/.venv/bin/python -m experiments.tracing evaluate \\
        --checkpoint artifacts/gru-smoke --output artifacts/gru-smoke/eval.json
"""

import argparse
import json
from pathlib import Path

from experiments.tracing.train import evaluate_checkpoint, train_synthetic


def _metric(report: dict[str, object], section: str, name: str) -> object:
    block = report[section]
    if isinstance(block, dict):
        return block.get(name)
    return None


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.tracing", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train", help="Train a tiny synthetic GRU and compare it with BKT")
    train.add_argument("--synthetic", action="store_true", required=True)
    train.add_argument("--seed", type=int, required=True)
    train.add_argument("--epochs", type=int, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--n-train", type=int, default=4)
    train.add_argument("--n-heldout", type=int, default=2)
    train.add_argument("--length", type=int, default=6)
    train.add_argument("--graph-features", action="store_true")
    evaluate = commands.add_parser(
        "evaluate", help="Reload a checkpoint and score held-out targets"
    )
    evaluate.add_argument("--checkpoint", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "train":
        report = train_synthetic(
            args.output,
            seed=args.seed,
            epochs=args.epochs,
            n_train=args.n_train,
            n_heldout=args.n_heldout,
            length=args.length,
            graph_features=args.graph_features,
        )
        _print(
            {
                "execution_status": report["execution_status"],
                "parameter_l1_delta": report["parameter_l1_delta"],
                "target_ids_equal": report["target_ids_equal"],
                "reload": report["reload"],
                "gru_log_loss": _metric(report, "gru", "log_loss"),
                "bkt_log_loss": _metric(report, "bkt", "log_loss"),
                "output": str(args.output),
            }
        )
        return 0
    report = evaluate_checkpoint(args.checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    _print({"execution_status": report["execution_status"], "output": str(args.output)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
