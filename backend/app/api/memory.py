"""Learner-scoped memory layers and the bounded tutor context built from them."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ScopedRepo
from app.api.errors import ApiError, ErrorEnvelope
from app.clock import utc_now
from app.graph.curriculum import UnknownConceptError
from app.inference.context import build_tutor_context
from app.learner.memory import memory_layers
from app.schemas.context import TutorContext
from app.schemas.memory import MAX_LAYER_ITEMS, MemoryLayers

router = APIRouter(prefix="/memory", tags=["memory"])

_ID_PATTERN = r"^[A-Za-z0-9_.:-]+$"
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
}
OptionalSessionId = Annotated[
    str | None, Query(min_length=1, max_length=64, pattern=_ID_PATTERN)
]


@router.get(
    "/layers",
    response_model=MemoryLayers,
    responses=_ERRORS,
    summary="Own evidence, beliefs, preferences, session context, notes and persona, by layer",
)
def get_memory_layers(
    repo: ScopedRepo,
    session_id: OptionalSessionId = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LAYER_ITEMS)] = 20,
) -> MemoryLayers:
    return memory_layers(repo, utc_now(), session_id=session_id, limit=limit)


@router.get(
    "/context",
    response_model=TutorContext,
    responses=_ERRORS,
    summary="The bounded context a tutor turn on this concept would send to a provider",
)
def get_tutor_context(
    repo: ScopedRepo,
    concept_id: Annotated[str, Query(min_length=1, max_length=64, pattern=_ID_PATTERN)],
    session_id: OptionalSessionId = None,
) -> TutorContext:
    try:
        return build_tutor_context(repo, concept_id, utc_now(), session_id=session_id)
    except UnknownConceptError as error:
        raise ApiError(404, "unknown_concept", "No such curriculum concept.") from error
