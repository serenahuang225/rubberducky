"""Bounded tutor context and final provider-request budgets (VAL-MEM-002)."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db.database import Database
from app.db.models import MisconceptionHypothesisRow
from app.db.seed import DEMO_LEARNER_ADA, DEMO_LEARNER_BEN, seed_uuid
from app.graph.curriculum import UnknownConceptError
from app.inference.context import build_tutor_context, serialize_payload, uncitable_ids
from app.inference.request import (
    InsufficientContextError,
    ProviderBudget,
    ProviderBudgetError,
    build_provider_request,
)
from app.inference.tokens import CallableTokenCounter
from app.schemas.context import ContextBudget, TutorContext
from tests.memory_fixtures import DISTRIBUTION, add_learner, overfull_history, scoped

BACKEND_DIR = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
LEARNER = "fixture-overfull"


@pytest.fixture
def overfull(database: Database) -> dict[str, object]:
    with database.transaction() as db:
        return overfull_history(db, LEARNER, NOW)


def build(database: Database, learner_id: str = LEARNER, **kwargs: object) -> TutorContext:
    with database.transaction() as db:
        return build_tutor_context(scoped(db, learner_id), DISTRIBUTION, NOW, **kwargs)  # type: ignore[arg-type]


def items(context: TutorContext, kind: str) -> list[str]:
    return [item.ref for item in context.payload.items if item.kind == kind]


def omitted(context: TutorContext) -> dict[str, int]:
    return {f"{o.kind}/{o.reason}": o.count for o in context.payload.omitted}


def test_overfull_history_selects_recent_relevant_evidence_not_the_lifetime_transcript(
    database: Database, overfull: dict[str, object]
) -> None:
    context = build(database)
    observation_ids: list[str] = overfull["observation_ids"]  # type: ignore[assignment]

    # Six interleaved evidence links (newest first per polarity) and six recent observations.
    assert items(context, "evidence") == [
        f"{LEARNER}-link-{day:03d}" for day in (0, 5, 10, 15, 20, 25)
    ]
    polarities = [i.polarity for i in context.payload.items if i.kind == "evidence"]
    assert polarities == ["supports", "contradicts"] * 3
    assert items(context, "recent_observation") == [
        observation_ids[day] for day in (1, 2, 3, 4, 6, 7)
    ]
    assert items(context, "hypothesis") == [f"{LEARNER}-hyp"]
    assert set(items(context, "related_concept")) == {
        "concept.grouping",
        "concept.multiplication",
        "concept.linear_equations",
    }
    # 400 observations exist; the 340 outside the 60-day window are only counted.
    assert omitted(context) == {
        "evidence/selection_bound": 30,
        "recent_observation/selection_bound": 48,
        "recent_observation/outside_window": 340,
    }
    for old in observation_ids[60:]:
        assert old not in context.serialized
    assert context.payload.sufficiency == "sufficient"

    # The counting convention is explicit and measured on the exact serialized text.
    assert context.serialized == serialize_payload(context.payload)
    assert context.serialized_chars == len(context.serialized)
    assert context.token_counter == "utf8-bytes-upper-bound.v1"  # noqa: S105
    assert context.token_count == context.serialized_bytes == len(context.serialized.encode())
    assert context.within_budget and context.serialized_chars <= 16_000
    assert json.loads(context.serialized)["items"][0]["ref"] == DISTRIBUTION


def test_evidence_items_keep_ids_polarity_and_inference_labels(
    database: Database, overfull: dict[str, object]
) -> None:
    context = build(database)
    hypothesis = next(i for i in context.payload.items if i.kind == "hypothesis")
    assert hypothesis.status == "inference"
    assert hypothesis.facts["supporting_link_ids"] == [
        f"{LEARNER}-link-{d:03d}" for d in (0, 10, 20)
    ]
    assert hypothesis.facts["contradicting_link_ids"] == [
        f"{LEARNER}-link-{d:03d}" for d in (5, 15, 25)
    ]
    for item in context.payload.items:
        if item.kind == "evidence":
            assert item.status == "observed"
            assert item.hypothesis_id == f"{LEARNER}-hyp"
            assert item.source_ids[0] in context.citable_ids


def test_smaller_budget_reports_omissions_and_keeps_both_polarities_when_they_fit(
    database: Database, overfull: dict[str, object]
) -> None:
    full = build(database)
    budget = ContextBudget(max_serialized_chars=2_400)
    small = build(database, budget=budget)
    assert small.within_budget
    assert small.serialized_chars <= 2_400 < full.serialized_chars
    assert len(small.payload.items) < len(full.payload.items)
    budget_omissions = {k: v for k, v in omitted(small).items() if k.endswith("/budget")}
    assert budget_omissions, "budget truncation must be reported"
    assert small.payload.sufficiency in ("limited", "sufficient")

    kept_evidence = [i for i in small.payload.items if i.kind == "evidence"]
    assert len(kept_evidence) >= 2
    assert {i.polarity for i in kept_evidence} == {"supports", "contradicts"}
    # Summarized evidence lost its rationale text but not its IDs, polarity or status.
    for item in kept_evidence:
        if item.summarized:
            assert item.text is None and item.polarity and item.source_ids
            assert f"RATIONALE-{item.ref[-3:]}" not in small.serialized

    # Removed items are reported by ID to the operator, but are not citable or serialized.
    assert small.budget_omitted_ids
    for removed in small.budget_omitted_ids:
        assert removed not in small.citable_ids
        assert removed not in small.serialized
    assert uncitable_ids(small, small.budget_omitted_ids) == small.budget_omitted_ids


@pytest.mark.parametrize("limit", [700, 900, 1_200, 1_600, 2_000, 3_000, 5_000])
def test_every_budget_is_met_or_reported_insufficient(
    database: Database, overfull: dict[str, object], limit: int
) -> None:
    context = build(database, budget=ContextBudget(max_serialized_chars=limit))
    if context.payload.sufficiency == "insufficient":
        assert not context.within_budget
    else:
        assert context.within_budget and context.serialized_chars <= limit
        assert items(context, "target_concept") == [DISTRIBUTION]


def test_too_small_budget_is_insufficient_and_refused_for_the_provider(
    database: Database, overfull: dict[str, object]
) -> None:
    tiny = build(database, budget=ContextBudget(max_serialized_chars=200))
    assert tiny.payload.sufficiency == "insufficient"
    assert "budget_too_small" in tiny.payload.gaps
    assert not tiny.within_budget
    with database.transaction() as db, pytest.raises(InsufficientContextError):
        build_provider_request(
            scoped(db, LEARNER),
            concept_id=DISTRIBUTION,
            now=NOW,
            system_text="Tutor.",
            user_text="help",
            context_budget=ContextBudget(max_serialized_chars=200),
        )


def test_cold_start_learner_gets_a_limited_context_instead_of_invented_history(
    database: Database,
) -> None:
    with database.transaction() as db:
        add_learner(db, "fixture-cold", NOW - timedelta(days=1))
    context = build(database, learner_id="fixture-cold")
    assert context.payload.sufficiency == "limited"
    assert "no_prior_evidence_for_concept" in context.payload.gaps
    kinds = {item.kind for item in context.payload.items}
    assert kinds.isdisjoint({"hypothesis", "evidence", "recent_observation", "episodic_note"})


def test_foreign_invented_and_retracted_sources_are_not_citable(
    database: Database, overfull: dict[str, object]
) -> None:
    ada = build(database, learner_id=DEMO_LEARNER_ADA)
    ben = build(database, learner_id=DEMO_LEARNER_BEN)
    ada_hypothesis = seed_uuid("hypothesis:ada:1")
    assert ada_hypothesis in ada.citable_ids
    assert ada_hypothesis not in ben.citable_ids and ada_hypothesis not in ben.serialized
    assert all(i not in ben.serialized for i in ada.citable_ids if i.count("-") == 4)
    assert uncitable_ids(ben, [ada_hypothesis, "invented-id"]) == [ada_hypothesis, "invented-id"]

    with database.transaction() as db:
        row = db.get(MisconceptionHypothesisRow, ada_hypothesis)
        assert row is not None
        row.status = "retracted"
    after = build(database, learner_id=DEMO_LEARNER_ADA)
    assert ada_hypothesis not in after.citable_ids
    assert ada_hypothesis not in after.serialized
    assert uncitable_ids(after, [ada_hypothesis]) == [ada_hypothesis]


def test_unknown_concept_is_an_error_not_an_empty_context(database: Database) -> None:
    with database.transaction() as db, pytest.raises(UnknownConceptError):
        build_tutor_context(scoped(db, DEMO_LEARNER_ADA), "concept.unknown", NOW)


class CapturingProvider:
    """Stands in for an adapter: records exactly what would be sent."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def send(self, messages: list[dict[str, str]]) -> None:
        self.requests.append(json.dumps(messages))


def test_provider_ceiling_applies_to_the_final_assembled_request(
    database: Database, overfull: dict[str, object]
) -> None:
    # A different (non byte) counter proves the ceiling uses the adapter's own counting.
    counter = CallableTokenCounter("half-chars-test.v1", lambda text: len(text) // 2 + 1)
    provider_budget = ProviderBudget(
        context_window_tokens=1_400, max_output_tokens=300, max_request_chars=10_000
    )
    system_text = "You are a patient algebra tutor. " * 10
    with database.transaction() as db:
        request, context = build_provider_request(
            scoped(db, LEARNER),
            concept_id=DISTRIBUTION,
            now=NOW,
            system_text=system_text,
            user_text="I don't know what to do with the 3.",
            provider_budget=provider_budget,
            counter=counter,
        )
    provider = CapturingProvider()
    provider.send([m.model_dump() for m in request.messages])

    measured = sum(counter.count(m.content) for m in request.messages) + 8 * 2
    assert request.input_tokens == measured
    assert request.input_tokens + request.max_output_tokens <= 1_400
    assert request.request_chars == sum(len(m.content) for m in request.messages) <= 10_000
    assert request.token_counter == context.token_counter == "half-chars-test.v1"  # noqa: S105
    assert context.serialized in request.messages[1].content

    captured = provider.requests[0]
    observation_ids: list[str] = overfull["observation_ids"]  # type: ignore[assignment]
    assert context.budget_omitted_ids, "this budget must force truncation"
    for excluded in [*context.budget_omitted_ids, *observation_ids[60:]]:
        assert excluded not in captured
    for _, _, day in overfull["links"]:  # type: ignore[attr-defined]
        if f"{LEARNER}-link-{day:03d}" not in context.citable_ids:
            assert f"RATIONALE-{day:03d}" not in captured


def test_fixed_text_that_exhausts_the_window_is_refused(database: Database) -> None:
    with database.transaction() as db, pytest.raises(ProviderBudgetError):
        build_provider_request(
            scoped(db, DEMO_LEARNER_ADA),
            concept_id=DISTRIBUTION,
            now=NOW,
            system_text="x" * 2_000,
            user_text="help",
            provider_budget=ProviderBudget(context_window_tokens=1_024, max_output_tokens=256),
        )


def test_context_cli_prints_selected_ids_sizes_and_omissions(
    seeded_db_url: str, database: Database, overfull: dict[str, object]
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "--database-url",
            seeded_db_url,
            "memory",
            "context",
            "--learner",
            LEARNER,
            "--concept",
            DISTRIBUTION,
            "--now",
            NOW.isoformat(),
            "--max-chars",
            "2400",
            "--assemble",
            "--context-window",
            "4096",
            "--format",
            "json",
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    out = json.loads(result.stdout)
    context, request = out["context"], out["provider_request"]
    assert context["serialized_chars"] == len(context["serialized"]) <= 2_400
    assert context["payload"]["omitted"]
    assert f"{LEARNER}-link-000" in context["citable_ids"]
    assert request["input_tokens"] + request["max_output_tokens"] <= 4_096
