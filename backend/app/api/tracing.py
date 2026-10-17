"""Learner-scoped qualitative readiness derived from the independent BKT stream."""

from fastapi import APIRouter

from app.api.deps import ScopedRepo
from app.api.errors import ErrorEnvelope
from app.tracing.contracts import DEFAULT_PARAMETERS, ReadinessReport
from app.tracing.presentation import readiness_report
from app.tracing.replay import load_events, replay_events

router = APIRouter(prefix="/tracing", tags=["tracing"])


@router.get(
    "/readiness",
    response_model=ReadinessReport,
    responses={401: {"model": ErrorEnvelope}},
    summary="Qualitative, uncalibrated readiness and separate independent-transfer status",
)
def readiness(repo: ScopedRepo) -> ReadinessReport:
    # Read-only: replays raw evidence in memory and writes nothing.
    events = load_events(repo.db, repo.learner_id)
    predictor, _ = replay_events(repo.learner_id, events, DEFAULT_PARAMETERS)
    return readiness_report(events, predictor)
