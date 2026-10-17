"""Provider memory proposals are validated as a whole batch before any write (VAL-MEM-001)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.database import Database
from app.db.models import (
    Base,
    MemoryEntryRow,
    PreferenceRow,
    TutorConfigurationRow,
)
from app.db.seed import DEMO_LEARNER_ADA, DEMO_LEARNER_BEN, seed_uuid
from app.inference.context import build_tutor_context
from app.learner.memory_updates import ProposalScope, apply_memory_updates, proposal_entry_id
from tests.memory_fixtures import DISTRIBUTION, add_observation, scoped

NOW = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
ADA_OBSERVATION = seed_uuid("observation:ada:1:0")
ADA_HYPOTHESIS = seed_uuid("hypothesis:ada:1")
SEED_NOTE = seed_uuid("memory:ada:1")
BEN_OBSERVATION = "ben-observation-1"


@pytest.fixture
def setup(database: Database) -> dict[str, str]:
    with database.transaction() as db:
        ada = scoped(db, DEMO_LEARNER_ADA)
        session = ada.start_session("Practice", NOW - timedelta(minutes=5))
        ended = ada.start_session("Earlier", NOW - timedelta(hours=2))
        ada.end_session(ended.id, NOW - timedelta(hours=1))
        add_observation(
            db, DEMO_LEARNER_ADA, session.id, "ada-checkin", NOW,
            source_type="check_in", source_id=session.id, evidence_kind="self_report",
            concept_id=None, correct=None, confidence=1.0,
        )  # fmt: skip
        ben = scoped(db, DEMO_LEARNER_BEN)
        ben_session = ben.start_session("Ben", NOW - timedelta(minutes=5))
        add_observation(db, DEMO_LEARNER_BEN, ben_session.id, BEN_OBSERVATION, NOW)
        deleted = MemoryEntryRow(
            id="ada-deleted-note",
            schema_version="memory-entry.v1",
            learner_id=DEMO_LEARNER_ADA,
            session_id=None,
            layer="episodic_note",
            content="[deleted]",
            evidence_kind="inference",
            confidence=0.5,
            source_ids=[ADA_OBSERVATION],
            status="deleted",
            review_at=None,
            expires_at=None,
            origin="learner",
            turn_id=None,
            supersedes_id=None,
            provenance="submitted",
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(deleted)
    return {"session": session.id, "ended": ended.id, "ben_session": ben_session.id}


def note(**overrides: Any) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "operation": "create_episodic_note",
        "learner_id": DEMO_LEARNER_ADA,
        "content": "May benefit from a grouping picture before symbols.",
        "evidence_kind": "inference",
        "confidence": 0.5,
        "source_ids": [ADA_OBSERVATION],
        "review_at": (NOW + timedelta(days=14)).isoformat(),
    }
    proposal.update(overrides)
    return proposal


def session_context(session_id: str, **overrides: Any) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "operation": "create_session_context",
        "learner_id": DEMO_LEARNER_ADA,
        "session_id": session_id,
        "content": "Said they are tired today.",
        "evidence_kind": "self_report",
        "confidence": 0.9,
        "source_ids": ["ada-checkin"],
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
    }
    proposal.update(overrides)
    return proposal


def snapshot(database: Database) -> dict[str, object]:
    """Every table's row count plus the full contents of the layers a proposal could target."""
    with database.transaction() as db:
        counts = {
            table.name: db.execute(select(func.count()).select_from(table)).scalar_one()
            for table in Base.metadata.sorted_tables
        }
        memories = sorted(
            (r.id, r.status, r.content, r.updated_at)
            for r in db.execute(select(MemoryEntryRow)).scalars()
        )
        preferences = sorted(
            (r.id, r.key, str(r.value), r.updated_at)
            for r in db.execute(select(PreferenceRow)).scalars()
        )
        personas = sorted(
            (r.id, r.personality, r.last_changed_at)
            for r in db.execute(select(TutorConfigurationRow)).scalars()
        )
    return {"counts": counts, "memories": memories, "prefs": preferences, "personas": personas}


def apply(
    database: Database,
    proposals: list[Any],
    session_id: str | None,
    turn_id: str | None = "turn-1",
    citable: frozenset[str] | None = None,
) -> Any:
    with database.transaction() as db:
        return apply_memory_updates(
            scoped(db, DEMO_LEARNER_ADA),
            proposals,
            ProposalScope(session_id=session_id, turn_id=turn_id, citable_source_ids=citable),
            NOW,
        )


def test_valid_batch_is_applied_with_origin_turn_and_deterministic_ids(
    database: Database, setup: dict[str, str]
) -> None:
    result = apply(database, [session_context(setup["session"]), note()], setup["session"])
    assert result.status == "applied"
    assert result.applied_ids == [
        proposal_entry_id(DEMO_LEARNER_ADA, "turn-1", 0),
        proposal_entry_id(DEMO_LEARNER_ADA, "turn-1", 1),
    ]
    with database.transaction() as db:
        context_row = db.get(MemoryEntryRow, result.applied_ids[0])
        note_row = db.get(MemoryEntryRow, result.applied_ids[1])
        assert context_row is not None and note_row is not None
        assert context_row.layer == "session_context" and context_row.session_id == setup["session"]
        assert note_row.layer == "episodic_note" and note_row.review_at is not None
        for row in (context_row, note_row):
            assert row.origin == "tutor_proposal" and row.turn_id == "turn-1"
            assert row.provenance == "submitted" and row.status == "active"

    # Retrying the same turn replays instead of duplicating.
    before = snapshot(database)
    replay = apply(database, [session_context(setup["session"]), note()], setup["session"])
    assert replay.status == "applied" and replay.applied_ids == []
    assert replay.replayed_ids == result.applied_ids
    assert snapshot(database) == before

    # The same turn with different content is a conflict and changes nothing.
    conflict = apply(database, [session_context(setup["session"]), note(content="Different.")],
                     setup["session"])  # fmt: skip
    assert conflict.status == "rejected"
    assert [r.code for r in conflict.rejections] == ["conflicting_replay"]
    assert snapshot(database) == before


def _rejections(setup: dict[str, str]) -> list[tuple[str, list[Any], str]]:
    s = setup["session"]
    return [
        ("foreign-source", [note(source_ids=[BEN_OBSERVATION])], "unknown_source"),
        ("invented-source", [note(source_ids=["made-up-id"])], "unknown_source"),
        ("deleted-source", [note(source_ids=["ada-deleted-note"])], "unknown_source"),
        ("foreign-learner", [note(learner_id=DEMO_LEARNER_BEN)], "foreign_learner"),
        ("other-session", [session_context(setup["ended"])], "invalid_scope"),
        ("foreign-session", [session_context(setup["ben_session"])], "invalid_scope"),
        ("expires-too-late", [session_context(
            s, expires_at=(NOW + timedelta(days=2)).isoformat())], "invalid_expiry"),
        ("already-expired", [session_context(
            s, expires_at=(NOW - timedelta(minutes=1)).isoformat())], "invalid_expiry"),
        ("review-too-soon", [note(review_at=(NOW + timedelta(hours=1)).isoformat())],
         "invalid_expiry"),
        ("review-too-late", [note(review_at=(NOW + timedelta(days=400)).isoformat())],
         "invalid_expiry"),
        ("naive-time", [note(review_at="2026-10-20T10:00:00")], "schema_invalid"),
        ("self-report-without-report", [note(evidence_kind="self_report")],
         "unsupported_evidence_kind"),
        ("observed-work-claim", [note(evidence_kind="observed_work")], "schema_invalid"),
        ("overconfident", [note(confidence=0.95)], "confidence_too_high"),
        ("overwrite-preference", [{
            "operation": "set_preference", "learner_id": DEMO_LEARNER_ADA,
            "key": "wait_seconds", "value": 0}], "schema_invalid"),
        ("overwrite-evidence", [note(table="observations", target_id=ADA_OBSERVATION)],
         "schema_invalid"),
        ("rewrite-note", [note(id=SEED_NOTE)], "schema_invalid"),
        ("persona-change", [note(layer="persona", personality="mildly_sassy")],
         "schema_invalid"),
        ("curriculum-edge", [{
            "operation": "add_prerequisite_edge", "learner_id": DEMO_LEARNER_ADA,
            "prerequisite_id": DISTRIBUTION, "concept_id": "concept.multiplication"}],
         "schema_invalid"),
        ("flag-foreign-note", [{
            "operation": "flag_note_for_review", "learner_id": DEMO_LEARNER_ADA,
            "memory_id": "ben-note", "reason": "Outdated", "source_ids": [ADA_OBSERVATION]}],
         "unknown_target"),
        ("duplicate", [note(), note()], "duplicate_proposal"),
        ("too-many", [note(content=f"Note {i}") for i in range(6)], "too_many_proposals"),
    ]  # fmt: skip


REJECTION_IDS = [case[0] for case in _rejections({"session": "", "ended": "", "ben_session": ""})]


@pytest.mark.parametrize("case_id", REJECTION_IDS)
def test_invalid_proposals_reject_the_whole_batch_without_partial_effects(
    database: Database, setup: dict[str, str], case_id: str
) -> None:
    _, proposals, code = next(c for c in _rejections(setup) if c[0] == case_id)
    before = snapshot(database)
    # A valid proposal first proves nothing from a rejected batch is written.
    batch = proposals if case_id == "too-many" else [session_context(setup["session"]),
                                                     *proposals]  # fmt: skip
    result = apply(database, batch, setup["session"])
    assert result.status == "rejected"
    assert result.applied_ids == []
    assert code in [r.code for r in result.rejections]
    assert snapshot(database) == before


def test_sources_must_appear_in_the_context_the_provider_saw(
    database: Database, setup: dict[str, str]
) -> None:
    with database.transaction() as db:
        context = build_tutor_context(
            scoped(db, DEMO_LEARNER_ADA), DISTRIBUTION, NOW, session_id=setup["session"]
        )
    citable = frozenset(context.citable_ids)
    assert ADA_OBSERVATION in citable
    before = snapshot(database)
    # The check-in is Ada's own record, but it was not part of this context.
    hidden = apply(
        database, [session_context(setup["session"])], setup["session"], citable=citable
    )
    assert [r.code for r in hidden.rejections] == ["source_not_in_context"]
    assert snapshot(database) == before
    shown = apply(database, [note()], setup["session"], citable=citable)
    assert shown.status == "applied"


def test_flag_for_review_changes_only_the_status_of_an_own_note(
    database: Database, setup: dict[str, str]
) -> None:
    flag = {
        "operation": "flag_note_for_review",
        "learner_id": DEMO_LEARNER_ADA,
        "memory_id": SEED_NOTE,
        "reason": "Learner solved a transfer item since.",
        "source_ids": [ADA_OBSERVATION],
    }
    with database.transaction() as db:
        original = db.get(MemoryEntryRow, SEED_NOTE)
        assert original is not None
        content, sources = original.content, list(original.source_ids)
    result = apply(database, [flag], setup["session"])
    assert result.status == "applied" and result.applied_ids == [SEED_NOTE]
    with database.transaction() as db:
        row = db.get(MemoryEntryRow, SEED_NOTE)
        assert row is not None
        assert row.status == "needs_review" and row.content == content
        assert list(row.source_ids) == sources
    again = apply(database, [flag], setup["session"], turn_id="turn-2")
    assert again.status == "applied" and again.replayed_ids == [SEED_NOTE]


def test_empty_batch_is_a_no_op(database: Database, setup: dict[str, str]) -> None:
    before = snapshot(database)
    assert apply(database, [], setup["session"]).status == "empty"
    assert snapshot(database) == before
