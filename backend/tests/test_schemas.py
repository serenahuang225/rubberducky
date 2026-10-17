import math
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.db.seed import DEMO_LEARNER_ADA, all_seed_records, seed_uuid
from app.schemas import (
    ENTITY_CONTRACTS,
    ContractModel,
    MasteryEstimate,
    Observation,
    PrerequisiteEdge,
    SceneObject,
    Session,
    TransferCheck,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SESSION_ID = seed_uuid("session:ada:1")


def extra_records() -> list[ContractModel]:
    return [
        MasteryEstimate(
            id="estimate-1",
            learner_id=DEMO_LEARNER_ADA,
            concept_id="concept.distribution",
            algorithm="bkt",
            algorithm_version="bkt.v1",
            parameter_version="hand-uncalibrated.v1",
            p_known=0.38,
            source_observation_ids=[seed_uuid("observation:ada:1:0")],
            provenance="submitted",
            computed_at=NOW,
        ),
        TransferCheck(
            id="transfer-1",
            learner_id=DEMO_LEARNER_ADA,
            session_id=SESSION_ID,
            attempt_id=seed_uuid("attempt:ada:1"),
            problem_id="problem.transfer_3x_minus_2_eq_12",
            independent=True,
            outcome="unknown",
            provenance="submitted",
            assessed_at=NOW,
        ),
        SceneObject(
            id="scene-1",
            learner_id=DEMO_LEARNER_ADA,
            session_id=SESSION_ID,
            author_role="tutor",
            semantic_role="grouping_mark",
            kind="bracket",
            payload={"x": 10, "y": 20},
            provenance="submitted",
            created_at=NOW,
        ),
    ]


def all_examples() -> list[ContractModel]:
    return [*all_seed_records(), *extra_records()]


def test_example_matrix_covers_every_required_entity() -> None:
    covered = {type(record).__name__ for record in all_examples()}
    assert covered == set(ENTITY_CONTRACTS)


@pytest.mark.parametrize("record", all_examples(), ids=lambda r: type(r).__name__)
def test_records_round_trip_through_json_with_stable_ids_and_utc(record: ContractModel) -> None:
    restored = type(record).model_validate_json(record.model_dump_json())
    assert restored == record
    for value in restored.model_dump().values():
        if isinstance(value, datetime):
            assert value.utcoffset() == timedelta(0)


@pytest.mark.parametrize("record", all_examples(), ids=lambda r: type(r).__name__)
def test_unsupported_schema_version_is_rejected(record: ContractModel) -> None:
    data = record.model_dump()
    data["schema_version"] = data["schema_version"].replace(".v1", ".v2")
    with pytest.raises(ValidationError, match="schema_version"):
        type(record).model_validate(data)


def _observation(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "obs-1",
        "learner_id": DEMO_LEARNER_ADA,
        "session_id": SESSION_ID,
        "source_type": "step",
        "source_id": "step-1",
        "evidence_kind": "observed_work",
        "confidence": 0.8,
        "provenance": "submitted",
        "observed_at": NOW,
        "recorded_at": NOW,
    }
    return {**base, **overrides}


def test_missing_correctness_and_latency_stay_absent() -> None:
    observation = Observation.model_validate(_observation())
    assert observation.correct is None
    assert observation.latency_ms is None
    restored = Observation.model_validate_json(observation.model_dump_json())
    assert restored.correct is None and restored.latency_ms is None


@pytest.mark.parametrize("confidence", [math.nan, math.inf, -math.inf, -0.01, 1.01, "high"])
def test_invalid_confidence_is_rejected(confidence: object) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        Observation.model_validate(_observation(confidence=confidence))


def test_invalid_evidence_kind_is_rejected() -> None:
    with pytest.raises(ValidationError, match="evidence_kind"):
        Observation.model_validate(_observation(evidence_kind="hunch"))


def test_invalid_provenance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        Observation.model_validate(_observation(provenance="imported"))


@pytest.mark.parametrize("stamp", [datetime(2026, 10, 1, 12, 0), "2026-10-01T12:00:00"])
def test_naive_timestamps_are_rejected(stamp: object) -> None:
    with pytest.raises(ValidationError, match="observed_at"):
        Observation.model_validate(_observation(observed_at=stamp))


def test_aware_timestamps_are_normalized_to_utc() -> None:
    pacific = timezone(timedelta(hours=-7))
    observation = Observation.model_validate(
        _observation(observed_at=datetime(2026, 10, 1, 5, 0, tzinfo=pacific))
    )
    assert observation.observed_at == NOW
    assert observation.observed_at.tzinfo == UTC


def test_self_report_cannot_carry_correctness() -> None:
    with pytest.raises(ValidationError, match="correctness"):
        Observation.model_validate(
            _observation(evidence_kind="self_report", source_type="check_in", correct=True)
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Observation.model_validate(_observation(diagnosis="frustrated"))


def test_prerequisite_self_loop_is_rejected() -> None:
    with pytest.raises(ValidationError, match="own prerequisite"):
        PrerequisiteEdge(
            id="e", prerequisite_id="concept.a", concept_id="concept.a", created_at=NOW
        )


def test_session_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValidationError, match="ended_at"):
        Session(
            id="s",
            learner_id=DEMO_LEARNER_ADA,
            status="ended",
            provenance="submitted",
            started_at=NOW,
            ended_at=NOW - timedelta(seconds=1),
        )
