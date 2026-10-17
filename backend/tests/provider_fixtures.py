"""Shared fixtures for the production provider adapter tests.

Every adapter test runs with outbound sockets blocked (``no_network``), so a test that
reaches a real host fails instead of silently succeeding. Remote adapters are driven through
their actual SDK/HTTP stacks with an in-process transport, never a patched adapter method.
"""

import json
import re
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from app.db.database import Database
from app.db.seed import DEMO_LEARNER_ADA, FIXTURE_PROBLEM_ID
from app.inference.providers import DraftInputs, MockTutorProvider
from app.inference.remote import RemoteLimits
from app.inference.request import ProviderBudget, ProviderRequest, build_provider_request
from app.pedagogy.policy import Persona, plan_check_in
from app.pedagogy.problems import problem_spec
from app.schemas.tutor import ProblemView, TutorDraft
from app.tutor.coordinator import SYSTEM_TEXT
from tests.memory_fixtures import scoped

NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
SESSION_REVISION = 1
TURN_ID = "turn-adapter-1"
SECRET = "sk-test-SECRET-0123456789"  # noqa: S105 - a fake canary, never a real credential


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, object]]]:
    """Refuse every outbound connection and name lookup; yields the attempts made."""
    attempts: list[tuple[str, object]] = []

    def refuse(label: str) -> Any:
        def blocked(*args: object, **kwargs: object) -> Any:
            attempts.append((label, args[1:2] or args[:1]))
            raise ConnectionRefusedError(f"outbound network is blocked in tests ({label})")

        return blocked

    monkeypatch.setattr(socket.socket, "connect", refuse("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("connect_ex"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    yield attempts


def make_inputs(
    database: Database,
    *,
    turn_id: str = TURN_ID,
    session_revision: int = SESSION_REVISION,
    budget: ProviderBudget | None = None,
) -> DraftInputs:
    """Real plan, real bounded context and a measured request for one check-in turn."""
    spec = problem_spec(FIXTURE_PROBLEM_ID)
    problem = ProblemView(
        problem_id=spec.problem_id,
        attempt_id="attempt-1",
        statement=spec.statement,
        kind=spec.kind,
        concept_id=spec.concept_id,
        statement_object_id="stmt-obj",
    )
    plan = plan_check_in(
        turn_id=turn_id,
        spec=spec,
        problem=problem,
        energy="ready",
        check_in_observation_id="obs-checkin",
        reminder_ids=[],
        persona=Persona(),
    )
    with database.transaction() as db:
        request, context = build_provider_request(
            scoped(db, DEMO_LEARNER_ADA),
            concept_id=plan.context_concept_id,
            now=NOW,
            system_text=SYSTEM_TEXT,
            user_text="Check-in: goal=practice; energy=ready.",
            provider_budget=budget,
        )
    return DraftInputs(
        plan=plan,
        request=request,
        context=context,
        learner_id=DEMO_LEARNER_ADA,
        session_id="session-1",
        session_revision=session_revision,
        learner_text="Check-in: goal=practice; energy=ready.",
        now=NOW,
    )


def valid_draft(inputs: DraftInputs) -> TutorDraft:
    """A complete, current draft for ``inputs`` (the mock renders plan-sanctioned wording)."""
    return MockTutorProvider().draft(inputs)


def valid_draft_json(inputs: DraftInputs, **overrides: Any) -> str:
    body = valid_draft(inputs).model_dump(mode="json")
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def reply_for_request(messages: list[dict[str, str]], utterance: str = "Let's begin.") -> str:
    """What a well-behaved model would answer: the contract's fixed fields plus its words."""
    system = next(m["content"] for m in messages if m["role"] == "system")
    match = re.search(r"Copy these fixed fields exactly: (\{.*?\})\. Add 'utterance'", system)
    assert match, "the draft contract is missing from the system message"
    body = json.loads(match.group(1))
    required = re.search(r"must contain every ID in (\[.*?\]) and may add", system)
    assert required, "the required evidence IDs are missing from the draft contract"
    body.update(
        utterance=utterance,
        evidence_ids=json.loads(required.group(1)),
        decision_justification="Follows the planned move.",
    )
    return json.dumps(body, ensure_ascii=False)


def fast_limits(**overrides: Any) -> RemoteLimits:
    values: dict[str, Any] = {
        "timeout_seconds": 5.0,
        "max_attempts": 3,
        "backoff_seconds": 0.0,
        "max_output_tokens": 512,
        "max_request_chars": 64_000,
    }
    values.update(overrides)
    return RemoteLimits(**values)


def request_json(request: ProviderRequest) -> str:
    return request.model_dump_json()


def settings_for(**overrides: object) -> Settings:
    return Settings.model_validate({"database_url": "sqlite://", **overrides})


def chunked(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]
