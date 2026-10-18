"""Remote task and deterministic scorers for a Chalk tutoring evaluation.

IMPORTING THIS MODULE DEPLOYS FUNCTIONS: each ``@chalkcompute.function`` below starts a
background deployment when it is defined. Nothing in the application, the health route,
the CLI parser or the tests imports it. Only ``chalk_adapter.load_remote_functions`` does,
and only on the explicit ``evaluation chalk-run --confirm-live`` path after every
activation check has passed. Keep the definitions at module level (Chalk workers import
this module by name); put anything with side effects behind a function, never here.

The scorers apply the same stdlib-only rubric as the local run (``rubric.py``) so a remote
score can be compared with the local one for the same row.
"""

import json

import chalkcompute

from app.tutoring_eval.rubric import RUBRIC_VERSION

ScorerResults = list[chalkcompute.EvaluationScorerResult]


def _score(
    dimension: str, output: str, rubric_context_json: str, cited_json: str, claim: str
) -> ScorerResults:
    from app.tutoring_eval.rubric import score_dimension

    value, detail = score_dimension(
        dimension,
        output,
        json.loads(rubric_context_json),
        cited_source_ids=[str(item) for item in json.loads(cited_json)],
        claimed_revealed={"true": True, "false": False}.get(claim),
    )
    if value is None:
        # Not applicable to this turn: emit no score rather than a made-up one.
        return []
    return [
        chalkcompute.EvaluationScorerResult(
            score=value,
            metadata={"detail": detail, "kind": "deterministic", "rubric_version": RUBRIC_VERSION},
        )
    ]


@chalkcompute.function
def tutoring_replay_candidate(candidate_text: str) -> str:
    # The candidate already ran locally; the remote task only hands its reply to the scorers.
    return candidate_text


@chalkcompute.function
def tutoring_score_math(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score("math", output, rubric_context_json, cited_source_ids_json, answer_revealed_claim)


@chalkcompute.function
def tutoring_score_diagnosis(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score(
        "diagnosis", output, rubric_context_json, cited_source_ids_json, answer_revealed_claim
    )


@chalkcompute.function
def tutoring_score_disclosure(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score(
        "disclosure", output, rubric_context_json, cited_source_ids_json, answer_revealed_claim
    )


@chalkcompute.function
def tutoring_score_hint_specificity(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score(
        "hint_specificity",
        output,
        rubric_context_json,
        cited_source_ids_json,
        answer_revealed_claim,
    )


@chalkcompute.function
def tutoring_score_hint_usefulness(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score(
        "hint_usefulness", output, rubric_context_json, cited_source_ids_json, answer_revealed_claim
    )


@chalkcompute.function
def tutoring_score_respect(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score(
        "respect", output, rubric_context_json, cited_source_ids_json, answer_revealed_claim
    )


@chalkcompute.function
def tutoring_score_memory_grounding(
    output: str, rubric_context_json: str, cited_source_ids_json: str, answer_revealed_claim: str
) -> ScorerResults:
    return _score(
        "memory_grounding",
        output,
        rubric_context_json,
        cited_source_ids_json,
        answer_revealed_claim,
    )
