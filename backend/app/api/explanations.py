"""Offline learner explanations.

Mounted from the health router, which the app already includes. The handler reads settings
and returns a labeled pre-vetted spec. It does not open the tutor database or contact
Factory or Daytona.
"""

from fastapi import APIRouter, Request

from app.api.errors import ErrorEnvelope
from app.config import Settings
from app.interactives.learner import release_for_learner
from app.schemas.interactives import ExplanationRequest, LearnerExplanation

router = APIRouter(tags=["explanations"])


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not configured")
    return settings


@router.post(
    "/explanations/learner",
    response_model=LearnerExplanation,
    responses={422: {"model": ErrorEnvelope}},
    summary="Labeled pre-vetted explanation (does not contact Factory or Daytona)",
)
def learner_explanation(body: ExplanationRequest, request: Request) -> LearnerExplanation:
    return release_for_learner(_settings(request), body)
