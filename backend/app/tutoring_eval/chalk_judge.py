"""Optional model judge for a Chalk tutoring evaluation.

IMPORTING THIS MODULE DEPLOYS A JUDGE FUNCTION that calls a paid model through the Chalk
gateway when an evaluation runs. It is imported only by ``chalk_adapter.load_remote_functions``
when a judge was explicitly requested (``CHALK_JUDGE_ENABLED``, ``CHALK_JUDGE_MODEL`` and
``--include-judge``). The model name comes from ``TUTORING_EVAL_JUDGE_MODEL``, which the
adapter sets from settings just before importing; there is no default model.

A judge rating is a model opinion. It is reported as ``model_judged`` and never combined
with the deterministic rubric scores.
"""

import os

import chalkcompute
from pydantic import BaseModel, Field

JUDGE_MODEL_ENV = "TUTORING_EVAL_JUDGE_MODEL"
JUDGE_SCORER_NAME = "tutoring-judge"


class TutoringJudgeRating(BaseModel):
    score: float = Field(ge=0, le=1)
    reason: str


_INSTRUCTIONS = (
    "You rate one tutor reply to a learner. Score 0 to 1 for how well it helps the learner "
    "take their own next step without revealing a completed answer, is kind and specific "
    "to their work, and only refers to history that is shown. Give a one-sentence reason."
)

tutoring_judge = chalkcompute.scorers.llm_judge(
    TutoringJudgeRating,
    model=os.environ[JUDGE_MODEL_ENV],
    name=JUDGE_SCORER_NAME,
    instructions=_INSTRUCTIONS,
    inputs=("output", "learner_message", "history_json"),
    completion_kwargs={"temperature": 0, "max_tokens": 200},
    image=chalkcompute.Image.debian_slim("3.12").pip_install(["pydantic"]),
)
