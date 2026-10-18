"""``python -m app.cli interactives ...``: inspect and exercise the explanation pipeline.

Every command is local and read-only except ``generate --confirm-live``, which is refused
unless Factory and Daytona are explicitly enabled *and* configured, and which then contacts
both services. With the default (disabled) configuration ``generate`` returns the labeled
pre-vetted fallback and starts nothing.

Examples (from ``backend/``, with ``python`` = ``.venv/bin/python``):
    python -m app.cli interactives status
    python -m app.cli interactives prevetted --component grouping
    python -m app.cli interactives validate --spec-file spec.json
    python -m app.cli interactives generate \
        --concept concept.distribution --misconception "Multiplies only the first term"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.config import get_settings
from app.interactives import trusted_checks
from app.interactives.fallback import PREVETTED_SPECS
from app.interactives.pipeline import pipeline_from_settings
from app.interactives.status import describe_interactive_integrations
from app.schemas.interactives import MAX_SPEC_JSON_CHARS, ExplanationRequest, ExplanationSpec


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def cmd_status(_args: argparse.Namespace) -> int:
    _print(describe_interactive_integrations(get_settings()).model_dump(mode="json"))
    return 0


def cmd_prevetted(args: argparse.Namespace) -> int:
    spec = PREVETTED_SPECS[args.component]
    report = trusted_checks.check_spec(spec.model_dump(mode="json"))
    _print(
        {
            "label": "Pre-vetted (not generated)",
            "spec": spec.model_dump(mode="json"),
            "trusted_checks": report,
        }
    )
    return 0 if report["passed"] else 1


def cmd_validate(args: argparse.Namespace) -> int:
    text = Path(args.spec_file).read_text(encoding="utf-8")
    if len(text) > MAX_SPEC_JSON_CHARS:
        _print({"valid": False, "error": "spec exceeds the payload limit"})
        return 1
    try:
        raw = json.loads(text)
    except ValueError:
        _print({"valid": False, "error": "spec is not JSON"})
        return 1
    report = trusted_checks.check_spec(raw)
    try:
        ExplanationSpec.model_validate(raw)
        contract_valid = True
    except ValidationError:
        contract_valid = False
    # A spec is releasable only when both independent implementations accept it.
    _print(
        {
            "valid": contract_valid and report["passed"],
            "contract_valid": contract_valid,
            "trusted_checks": report,
        }
    )
    return 0 if contract_valid and report["passed"] else 1


def cmd_generate(args: argparse.Namespace) -> int:
    pipeline = pipeline_from_settings(get_settings())
    contacts_services = pipeline.generator is not None or pipeline.checker is not None
    if contacts_services and not args.confirm_live:
        _print(
            {
                "refused": "configured integrations would contact Factory and Daytona",
                "next": "re-run with --confirm-live, or leave the integrations disabled",
            }
        )
        return 2
    request = ExplanationRequest(
        concept_id=args.concept,
        misconception=args.misconception,
        context_note=args.context,
        preferred_component=args.component,
    )
    released = asyncio.run(pipeline.release(request))
    _print(released.model_dump(mode="json"))
    return 0


def add_interactives_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    root = sub.add_parser(
        "interactives", help="Generated native explanations: status, validation and release"
    )
    commands = root.add_subparsers(dest="interactives_command", required=True)
    commands.add_parser(
        "status", help="Factory/Daytona activation status (no network)"
    ).set_defaults(handler=cmd_status)
    prevetted = commands.add_parser("prevetted", help="Show a pre-vetted spec and its checks")
    prevetted.add_argument("--component", choices=sorted(PREVETTED_SPECS), default="distribution")
    prevetted.set_defaults(handler=cmd_prevetted)
    validate = commands.add_parser("validate", help="Check a spec file locally")
    validate.add_argument("--spec-file", required=True)
    validate.set_defaults(handler=cmd_validate)
    generate = commands.add_parser(
        "generate", help="Release a generated explanation, or the labeled fallback"
    )
    generate.add_argument(
        "--concept", choices=("concept.distribution", "concept.grouping"), required=True
    )
    generate.add_argument("--misconception", required=True)
    generate.add_argument("--context", default="")
    generate.add_argument("--component", choices=sorted(PREVETTED_SPECS), default=None)
    generate.add_argument(
        "--confirm-live",
        action="store_true",
        help="Allow contacting configured Factory and Daytona (never needed when disabled)",
    )
    generate.set_defaults(handler=cmd_generate)


if __name__ == "__main__":
    sys.exit("run through: python -m app.cli interactives")
