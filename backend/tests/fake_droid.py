"""A stand-in ``droid`` executable that speaks the real stream-jsonrpc protocol.

``droid_sdk`` spawns it as a genuine subprocess through its own ``ProcessTransport``, so the
production adapter, its argv/cwd/environment and the SDK's JSON-RPC and structured-output
handling are all exercised. It never contacts a network: it reads ``scenario.json`` beside it
and writes every request, its environment and its working directory to ``record.jsonl``.
This is a transport fixture, not evidence about the real Factory service.
"""

import json
import stat
import sys
from pathlib import Path
from typing import Any

_SCRIPT = r"""#!__PYTHON__
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO = json.load(open(os.path.join(HERE, "scenario.json")))
RECORD = os.path.join(HERE, "record.jsonl")


def record(entry):
    with open(RECORD, "a") as handle:
        handle.write(json.dumps(entry) + "\n")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def notify(notification):
    send({"jsonrpc": "2.0", "factoryApiVersion": "1.0.0", "type": "notification",
          "method": "droid.session_notification", "params": {"notification": notification}})


def usage(credits):
    return {"inputTokens": 10, "outputTokens": 10, "cacheCreationTokens": 0,
            "cacheReadTokens": 0, "thinkingTokens": 0, "factoryCredits": credits}


def usage_update(credits):
    notify({"type": "session_token_usage_changed", "sessionId": "fake-session",
            "tokenUsage": usage(credits)})


def finish(turn_id, reason, credits=0.1):
    notify({"type": "agent_turn_completed", "reason": reason, "turnId": turn_id,
            "tokenUsage": usage(credits), "durationMs": 5})


record({"event": "start", "pid": os.getpid(), "argv": sys.argv[1:], "cwd": os.getcwd(),
        "env": dict(os.environ)})
if SCENARIO.get("mode") == "crash_on_start":
    sys.exit(3)

turn_id = None
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    params = message.get("params") or {}
    record({"event": "request", "method": method, "params": params})
    reply = {"type": "response", "id": message.get("id"), "jsonrpc": "2.0"}
    if method == "droid.initialize_session":
        reply["result"] = {
            "sessionId": "fake-session",
            "session": {"messages": []},
            "settings": {
                "modelId": params.get("modelId") or "fake-model",
                "reasoningEffort": params.get("reasoningEffort") or "low",
                "interactionMode": params.get("interactionMode") or "auto",
                "autonomyLevel": params.get("autonomyLevel") or "off",
                "systemPrompt": params.get("systemPrompt"),
                "restrictToolIds": params.get("restrictToolIds"),
                "disabledToolIds": params.get("disabledToolIds"),
            },
        }
        send(reply)
    elif method == "droid.add_user_message":
        reply["result"] = {}
        send(reply)
        turn_id = params.get("messageId")
        mode = SCENARIO.get("mode", "ok")
        if mode == "hang":
            continue
        for credits in SCENARIO.get("usage_updates", []):
            usage_update(credits)
        if mode == "hang_after_usage":
            continue
        if mode == "error_turn":
            finish(turn_id, "error")
        elif mode == "bad_reason":
            finish(turn_id, "model_authentication_failed")
        else:
            payload = SCENARIO.get("structured_output")
            if payload is not None:
                notify({"type": "structured_output", "messageId": turn_id,
                        "structuredOutput": payload})
            finish(turn_id, "completed", SCENARIO.get("credits", 0.1))
    elif method == "droid.interrupt_session":
        reply["result"] = {}
        send(reply)
        if turn_id is not None:
            finish(turn_id, "cancelled")
    else:
        reply["result"] = {}
        send(reply)
"""


def install_fake_droid(directory: Path, scenario: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "droid"
    script.write_text(_SCRIPT.replace("__PYTHON__", sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    write_scenario(directory, scenario)
    return script


def write_scenario(directory: Path, scenario: dict[str, Any]) -> None:
    (directory / "scenario.json").write_text(json.dumps(scenario))


def read_records(directory: Path) -> list[dict[str, Any]]:
    path = directory / "record.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]
