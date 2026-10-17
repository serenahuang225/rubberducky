"""Which raw observations enter the independent BKT stream, and why others do not.

Rules (version ``bkt-eligibility.v1``), checked in order:

1. The observation names a concept and carries a measured correctness value. Silence,
   tiredness, self-reports and unsupported/unknown verification have none.
2. It is a ``verified_assessment`` backed by an assessment record. Step-level observed work
   stays as raw evidence for hypotheses and feedback but is not a scored opportunity.
3. Explanation checks are judged by a rubric, not as a right/wrong response, so they are
   excluded.
4. The assessment outcome agrees with the observation's correctness.
5. The work was independent: the observation is not assisted, the assessment is marked
   independent, and no hint (in particular an answer-revealing one) was given in the
   attempt before the response. Later hints cannot reach back and taint earlier work.

An opportunity is one problem for one concept (``concept|problem``). Retries and replays of
the same problem therefore count at most once; a distinct transfer problem is a new
opportunity. Raw rows are only read, never changed.
"""

from collections.abc import Iterable

from app.db.models import AssessmentRow, HintRow, ObservationRow
from app.tracing.contracts import IneligibleReason, TracingEvent


def opportunity_key(concept_id: str, problem_id: str) -> str:
    return f"{concept_id}|{problem_id}"


def _reason(
    observation: ObservationRow,
    assessment: AssessmentRow | None,
    attempt_hints: Iterable[HintRow],
) -> IneligibleReason | None:
    if observation.concept_id is None:
        return "no_concept"
    if observation.correct is None:
        return "no_response_correctness"
    if observation.evidence_kind != "verified_assessment":
        return "not_verified_assessment"
    if observation.source_type != "assessment" or assessment is None:
        return "no_assessment_record"
    if assessment.kind == "explanation_check":
        return "explanation_not_response_opportunity"
    expected = "correct" if observation.correct else "incorrect"
    if assessment.outcome != expected:
        return "assessment_outcome_mismatch"
    # Only hints given before this response can have assisted it; a hint that follows
    # the work (for example corrective feedback after a wrong answer) must not reach back.
    hints = [hint for hint in attempt_hints if hint.given_at < observation.observed_at]
    if any(hint.answer_revealed for hint in hints):
        return "answer_revealed"
    if observation.assisted or not assessment.independent:
        return "assisted"
    if hints:
        return "hint_in_attempt"
    return None


def classify(
    observation: ObservationRow,
    assessment: AssessmentRow | None,
    attempt_hints: Iterable[HintRow] = (),
) -> TracingEvent:
    reason = _reason(observation, assessment, attempt_hints)
    key = None
    if reason is None and assessment is not None and observation.concept_id is not None:
        key = opportunity_key(observation.concept_id, assessment.problem_id)
    return TracingEvent.model_validate(
        {
            "observation_id": observation.id,
            "learner_id": observation.learner_id,
            "concept_id": observation.concept_id,
            "correct": observation.correct,
            "source_type": observation.source_type,
            "source_id": observation.source_id,
            "assessment_id": None if assessment is None else assessment.id,
            "assessment_kind": None if assessment is None else assessment.kind,
            "problem_id": None if assessment is None else assessment.problem_id,
            "opportunity_key": key,
            "eligible": reason is None,
            "ineligible_reason": reason,
            "provenance": observation.provenance,
            "observed_at": observation.observed_at,
        }
    )
