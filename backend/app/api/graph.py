"""Learner-scoped graph context: shared curriculum neighborhood plus own evidence."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ScopedRepo
from app.api.errors import ApiError, ErrorEnvelope
from app.clock import utc_now
from app.graph.context import build_graph_context
from app.graph.curriculum import UnknownConceptError
from app.schemas.graph import (
    MAX_CONTEXT_EVIDENCE,
    MAX_CONTEXT_HOPS,
    MAX_CONTEXT_HYPOTHESES,
    MAX_CONTEXT_NODES,
    GraphContext,
    GraphContextBounds,
)

router = APIRouter(prefix="/graph", tags=["graph"])

_DEFAULTS = GraphContextBounds()
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
}


@router.get(
    "/context",
    response_model=GraphContext,
    responses=_ERRORS,
    summary="Bounded curriculum neighborhood with the learner's support/contradiction evidence",
)
def graph_context(
    repo: ScopedRepo,
    concept_id: Annotated[str, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")],
    max_hops: Annotated[int, Query(ge=0, le=MAX_CONTEXT_HOPS)] = _DEFAULTS.max_hops,
    max_nodes: Annotated[int, Query(ge=1, le=MAX_CONTEXT_NODES)] = _DEFAULTS.max_nodes,
    max_hypotheses: Annotated[
        int, Query(ge=0, le=MAX_CONTEXT_HYPOTHESES)
    ] = _DEFAULTS.max_hypotheses,
    max_evidence: Annotated[int, Query(ge=0, le=MAX_CONTEXT_EVIDENCE)] = _DEFAULTS.max_evidence,
    max_age_days: Annotated[int | None, Query(ge=1, le=3650)] = None,
) -> GraphContext:
    bounds = GraphContextBounds(
        max_hops=max_hops,
        max_nodes=max_nodes,
        max_hypotheses=max_hypotheses,
        max_evidence=max_evidence,
        max_age_days=max_age_days,
    )
    try:
        return build_graph_context(repo, concept_id, utc_now(), bounds)
    except UnknownConceptError as error:
        raise ApiError(404, "unknown_concept", "No such curriculum concept.") from error
