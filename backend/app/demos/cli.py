"""``python -m app.cli demo``: print the fictional Chalk, Droid, and Daytona walkthrough.

Every command is local. Nothing is uploaded, deployed, or started.
"""

import argparse
import json

from app.demos.integrations import FictionalIntegrationDemos, build_fictional_integration_demos


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _section(demos: FictionalIntegrationDemos, which: str) -> dict[str, object]:
    if which == "all":
        return demos.model_dump(mode="json")
    return {
        "is_fictional": True,
        "live_services_contacted": False,
        "notice": demos.notice,
        which: getattr(demos, which).model_dump(mode="json"),
    }


def cmd_demo(args: argparse.Namespace) -> int:
    _print(_section(build_fictional_integration_demos(), args.which))
    return 0


def add_demo_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    demo = sub.add_parser(
        "demo",
        help="Fictional Chalk, Droid, and Daytona walkthrough (no network)",
    )
    demo.add_argument(
        "which",
        nargs="?",
        choices=("all", "chalk", "droid", "daytona"),
        default="all",
        help="Which fictional demo to print (default: all)",
    )
    demo.set_defaults(handler=cmd_demo)
