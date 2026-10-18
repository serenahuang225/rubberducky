"""Fictional demonstrations of Chalk, Factory Droid, and Daytona.

The Chalk section scores the repository's scripted tutor replies with the local rubric and
builds the dataset plan a cloud run would upload. The Droid section is an explanation written
in this repository. The Daytona section runs the repository's trusted checks on this machine.
No credential is read, and no upload, sandbox, subprocess, or credit is used.
"""

from typing import Annotated, Literal

from pydantic import Field

from app.interactives import trusted_checks
from app.schemas.common import ContractModel
from app.schemas.interactives import (
    CheckOutcome,
    DistributionSpec,
    ExplanationSpec,
    IntRange,
)
from app.tutoring_eval.candidates import fixture_candidate
from app.tutoring_eval.cases import CASE_SET_VERSION, build_fixture_cases
from app.tutoring_eval.chalk_adapter import build_dataset_rows
from app.tutoring_eval.contracts import DimensionSummary, ReplaySnapshot, RowResult
from app.tutoring_eval.replay import build_snapshots
from app.tutoring_eval.rubric import RUBRIC_VERSION
from app.tutoring_eval.runner import evaluate_candidate

NOTICE = (
    "Invented walkthrough. Chalk scores are the local rubric on scripted replies. "
    "The Droid explanation was written in this repository. Daytona checks are the same "
    "trusted checks run on this machine. No account, upload, sandbox, or credit was used."
)

PICTURE_LABEL = "Fictional demo picture. Factory and Daytona were not contacted."

DROID_SPEC = ExplanationSpec(
    concept_id="concept.distribution",
    title="The outside number reaches both parts",
    prompt="Change the outside number. What happens to both rectangles?",
    caption=(
        "A fictional learner wrote 3(x + 2) as 3x + 2. "
        "The outside number multiplies the x and the 2."
    ),
    manipulative=DistributionSpec(
        component="distribution",
        outer=IntRange(min=1, max=6, initial=3),
        left=IntRange(min=1, max=8, initial=1),
        right=IntRange(min=1, max=8, initial=2),
    ),
)

DROID_MISCONCEPTION = "Multiplies only the first term inside brackets"
DROID_CONTEXT = "Fictional learner Ada wrote 3(x + 2) as 3x + 2."
DROID_NOTES = ("Fictional note: both rectangles should grow together.",)


class DemoScore(ContractModel):
    dimension: str
    value: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None


class DemoTurn(ContractModel):
    scenario: str
    learner_message: str
    reply: str
    scores: list[DemoScore]


class ChalkCandidateDemo(ContractModel):
    candidate_name: str
    note: str
    errors: int
    dimensions: list[DimensionSummary]
    turns: list[DemoTurn] = Field(default_factory=list)


class ChalkDemo(ContractModel):
    title: Literal["Chalk tutoring evaluation"] = "Chalk tutoring evaluation"
    notice: str
    case_set_version: str
    rubric_version: str
    dataset_name: str
    dataset_rows: int
    uploaded: Literal[False] = False
    trained_model_result: Literal[False] = False
    learning_gain_claim: Literal[False] = False
    candidates: list[ChalkCandidateDemo]


class DroidDemo(ContractModel):
    title: Literal["Factory Droid explanation"] = "Factory Droid explanation"
    notice: str
    misconception: str
    context_note: str
    self_check_notes: list[str]
    factory_contacted: Literal[False] = False
    credits_spent: Literal[0] = 0
    picture_label: str
    spec: ExplanationSpec


class DaytonaDemo(ContractModel):
    title: Literal["Daytona sandbox check"] = "Daytona sandbox check"
    notice: str
    sandbox_id: Literal["sbx-fictional-demo"] = "sbx-fictional-demo"
    sandbox_created: Literal[False] = False
    spec_digest: str
    passed: bool
    checks: list[CheckOutcome]


class FictionalIntegrationDemos(ContractModel):
    schema_version: Literal["fictional-integration-demos.v1"] = "fictional-integration-demos.v1"
    is_fictional: Literal[True] = True
    live_services_contacted: Literal[False] = False
    notice: str = NOTICE
    chalk: ChalkDemo
    droid: DroidDemo
    daytona: DaytonaDemo


def _turns(snapshots: list[ReplaySnapshot], rows: list[RowResult]) -> list[DemoTurn]:
    by_key = {(snapshot.case_id, snapshot.turn_id): snapshot for snapshot in snapshots}
    turns: list[DemoTurn] = []
    for row in rows:
        if row.response is None:
            continue
        snapshot = by_key[(row.case_id, row.turn_id)]
        turns.append(
            DemoTurn(
                scenario=row.scenario,
                learner_message=snapshot.learner_message,
                reply=row.response.text,
                scores=[
                    DemoScore(dimension=score.dimension, value=score.value) for score in row.scores
                ],
            )
        )
    return turns


def _chalk(snapshots: list[ReplaySnapshot]) -> ChalkDemo:
    good = evaluate_candidate(fixture_candidate("good"), snapshots)
    leaky = evaluate_candidate(fixture_candidate("leaky"), snapshots)
    _, plan = build_dataset_rows(snapshots, good)
    return ChalkDemo(
        notice=(
            "Scores come from the local rubric. The dataset plan was built here and not "
            "uploaded. Scripted replies have no model latency, so latency stays missing."
        ),
        case_set_version=CASE_SET_VERSION,
        rubric_version=RUBRIC_VERSION,
        dataset_name=plan.dataset_name,
        dataset_rows=plan.row_count,
        candidates=[
            ChalkCandidateDemo(
                candidate_name=good.candidate_name,
                note="Scripted replies for a careful tutor on the fictional cases.",
                errors=good.errors,
                dimensions=good.dimensions,
                turns=_turns(snapshots, good.rows),
            ),
            ChalkCandidateDemo(
                candidate_name=leaky.candidate_name,
                note=(
                    "Scripted replies that give the answer and blame the learner. "
                    "Lower scores show the rubric, not a model."
                ),
                errors=leaky.errors,
                dimensions=leaky.dimensions,
            ),
        ],
    )


def _droid() -> DroidDemo:
    return DroidDemo(
        notice=(
            "This explanation is repository text for the demo. Factory Droid was not started, "
            "and the note below is not used as evidence that the picture is correct."
        ),
        misconception=DROID_MISCONCEPTION,
        context_note=DROID_CONTEXT,
        self_check_notes=list(DROID_NOTES),
        picture_label=PICTURE_LABEL,
        spec=DROID_SPEC,
    )


def _daytona() -> DaytonaDemo:
    report = trusted_checks.check_spec(DROID_SPEC.model_dump(mode="json"))
    checks = [CheckOutcome.model_validate(item) for item in report["checks"]]
    return DaytonaDemo(
        notice=(
            "These are the repository's trusted checks, run in this process. "
            "No Daytona sandbox was created, and nothing was deleted."
        ),
        spec_digest=report["spec_digest"],
        passed=bool(report["passed"]),
        checks=checks,
    )


def build_fictional_integration_demos() -> FictionalIntegrationDemos:
    snapshots = build_snapshots(build_fixture_cases())
    return FictionalIntegrationDemos(
        chalk=_chalk(snapshots),
        droid=_droid(),
        daytona=_daytona(),
    )
