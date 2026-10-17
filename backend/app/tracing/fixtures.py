"""A labeled fictional learner whose raw history exercises the BKT replay rules.

Two independent correct opportunities are separated by excluded or duplicate evidence: a
retry of the same problem, an answer-revealed assisted attempt, a tiredness check-in and a
transfer check whose verification was unsupported. With the default hand-set parameters
the replay yields 10/19 after the first opportunity and 0.82 after the second.
"""

from datetime import datetime, timedelta

from app.db.seed import (
    FIXTURE_PROBLEM_ID,
    SEED,
    SEED_EPOCH,
    TRANSFER_PROBLEM_ID,
    seed_uuid,
)
from app.schemas import (
    Assessment,
    Attempt,
    ContractModel,
    Hint,
    Learner,
    Observation,
    Session,
)

FIXTURE_ALIAS = "bkt-fixture"
FIXTURE_LEARNER_ID = seed_uuid("learner:bkt-fixture")
FIXTURE_CONCEPT_ID = "concept.linear_equations"
_BASE = SEED_EPOCH + timedelta(days=3)


def _at(minutes: int) -> datetime:
    return _BASE + timedelta(minutes=minutes)


def _scored_attempt(
    name: str,
    minute: int,
    problem_id: str,
    *,
    kind: str = "practice_check",
    outcome: str = "correct",
    independent: bool = True,
    assisted: bool = False,
    answer_revealing_hint: bool = False,
) -> list[ContractModel]:
    session_id = seed_uuid("session:bkt-fixture:1")
    attempt_id = seed_uuid(f"attempt:bkt-fixture:{name}")
    assessment_id = seed_uuid(f"assessment:bkt-fixture:{name}")
    records: list[ContractModel] = [
        Attempt(
            id=attempt_id,
            learner_id=FIXTURE_LEARNER_ID,
            session_id=session_id,
            problem_id=problem_id,
            provenance=SEED,
            started_at=_at(minute),
            completed_at=_at(minute + 3),
        )
    ]
    if answer_revealing_hint:
        records.append(
            Hint(
                id=seed_uuid(f"hint:bkt-fixture:{name}"),
                learner_id=FIXTURE_LEARNER_ID,
                session_id=session_id,
                attempt_id=attempt_id,
                concept_id=FIXTURE_CONCEPT_ID,
                level=4,
                answer_revealed=True,
                content="Worked solution shown: x = 4.",
                provenance=SEED,
                given_at=_at(minute + 1),
            )
        )
    records.append(
        Assessment.model_validate(
            {
                "id": assessment_id,
                "learner_id": FIXTURE_LEARNER_ID,
                "session_id": session_id,
                "attempt_id": attempt_id,
                "problem_id": problem_id,
                "kind": kind,
                "independent": independent,
                "outcome": outcome,
                "provenance": SEED,
                "assessed_at": _at(minute + 3),
            }
        )
    )
    records.append(
        Observation(
            id=seed_uuid(f"observation:bkt-fixture:{name}"),
            learner_id=FIXTURE_LEARNER_ID,
            session_id=session_id,
            source_type="assessment",
            source_id=assessment_id,
            evidence_kind="verified_assessment",
            concept_id=FIXTURE_CONCEPT_ID,
            correct=None if outcome == "unknown" else outcome == "correct",
            confidence=0.95 if outcome != "unknown" else 0.0,
            assisted=assisted,
            provenance=SEED,
            observed_at=_at(minute + 3),
            recorded_at=_at(minute + 3),
        )
    )
    return records


def bkt_fixture_records() -> list[ContractModel]:
    session_id = seed_uuid("session:bkt-fixture:1")
    return [
        Learner(
            id=FIXTURE_LEARNER_ID,
            display_name="BKT replay fixture (fictional demo learner)",
            is_fictional=True,
            provenance=SEED,
            created_at=_at(-10),
        ),
        Session(
            id=session_id,
            learner_id=FIXTURE_LEARNER_ID,
            status="ended",
            goal="Fictional replay fixture",
            provenance=SEED,
            started_at=_at(0),
            ended_at=_at(60),
        ),
        # 1: independent correct -> counted.
        *_scored_attempt("first", 1, FIXTURE_PROBLEM_ID),
        # 2: retry of the same problem -> duplicate opportunity.
        *_scored_attempt("retry", 6, FIXTURE_PROBLEM_ID),
        # 3: answer revealed by a hint -> assisted evidence only.
        *_scored_attempt(
            "revealed",
            11,
            FIXTURE_PROBLEM_ID,
            independent=False,
            assisted=True,
            answer_revealing_hint=True,
        ),
        # 4: a tiredness check-in is a self-report, never a correctness observation.
        Observation(
            id=seed_uuid("observation:bkt-fixture:tired"),
            learner_id=FIXTURE_LEARNER_ID,
            session_id=session_id,
            source_type="check_in",
            source_id=session_id,
            evidence_kind="self_report",
            concept_id=None,
            correct=None,
            confidence=0.8,
            provenance=SEED,
            observed_at=_at(16),
            recorded_at=_at(16),
        ),
        # 5: unsupported verification leaves correctness unknown.
        *_scored_attempt(
            "unsupported", 20, TRANSFER_PROBLEM_ID, kind="transfer_check", outcome="unknown"
        ),
        # 6: distinct independent transfer, correct -> counted.
        *_scored_attempt("transfer", 25, TRANSFER_PROBLEM_ID, kind="transfer_check"),
    ]
