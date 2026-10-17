"""Learner-scoped memory layers and the bounded tutor context built from them."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import ScopedRepo
from app.api.errors import ApiError, ErrorEnvelope, not_found
from app.clock import utc_now
from app.graph.curriculum import UnknownConceptError
from app.inference.context import build_tutor_context
from app.learner.corrections import (
    CorrectionError,
    correct_evidence,
    correct_note,
    delete_evidence,
    delete_hypothesis,
    delete_note,
)
from app.learner.inspection import explain_sources, inspect_memory
from app.learner.memory import memory_layers
from app.schemas.agency import (
    MAX_INSPECTION_ITEMS,
    CorrectEvidenceRequest,
    CorrectionReceipt,
    CorrectNoteRequest,
    DeletionReceipt,
    MemoryInspection,
    SourceExplanation,
)
from app.schemas.context import TutorContext
from app.schemas.memory import MAX_LAYER_ITEMS, MemoryLayers

router = APIRouter(prefix="/memory", tags=["memory"])

_ID_PATTERN = r"^[A-Za-z0-9_.:-]+$"
_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
}
_CHANGE_ERRORS: dict[int | str, dict[str, object]] = {**_ERRORS, 409: {"model": ErrorEnvelope}}
RecordId = Annotated[str, Path(min_length=1, max_length=64, pattern=_ID_PATTERN)]
OptionalSessionId = Annotated[str | None, Query(min_length=1, max_length=64, pattern=_ID_PATTERN)]


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


@router.get(
    "/inspect",
    response_model=MemoryInspection,
    responses=_ERRORS,
    summary="Private memory view: what is remembered, sources, uncertainty and why it matters",
)
def inspect(
    repo: ScopedRepo,
    session_id: OptionalSessionId = None,
    limit: Annotated[int, Query(ge=1, le=MAX_INSPECTION_ITEMS)] = 20,
) -> MemoryInspection:
    return inspect_memory(repo, utc_now(), limit=limit, session_id=session_id)


@router.get(
    "/sources/{source_id}",
    response_model=SourceExplanation,
    responses=_ERRORS,
    summary="Explain one cited source in plain language (own records only)",
)
def explain_source(source_id: RecordId, repo: ScopedRepo) -> SourceExplanation:
    explanation = explain_sources(repo, [source_id])[source_id]
    if not explanation.available:
        raise not_found()
    return explanation


def _changed(error: CorrectionError) -> ApiError:
    return ApiError(error.status_code, error.code, error.message)


@router.post(
    "/evidence/{observation_id}/correction",
    response_model=CorrectionReceipt,
    responses=_CHANGE_ERRORS,
    summary="Correct whether a piece of evidence was right; beliefs and estimates recompute",
)
def correct_evidence_route(
    observation_id: RecordId, body: CorrectEvidenceRequest, repo: ScopedRepo
) -> CorrectionReceipt:
    try:
        receipt = correct_evidence(repo, observation_id, body.correct, utc_now())
    except CorrectionError as error:
        repo.db.rollback()
        raise _changed(error) from error
    repo.db.commit()
    return receipt


@router.delete(
    "/evidence/{observation_id}",
    response_model=DeletionReceipt,
    responses=_ERRORS,
    summary="Delete a piece of evidence; dependents are removed and estimates recomputed",
)
def delete_evidence_route(observation_id: RecordId, repo: ScopedRepo) -> DeletionReceipt:
    receipt = delete_evidence(repo, observation_id, utc_now())
    repo.db.commit()
    return receipt


@router.post(
    "/notes/{memory_id}/correction",
    response_model=CorrectionReceipt,
    responses=_CHANGE_ERRORS,
    summary="Replace a note with your own wording; the original stops being current",
)
def correct_note_route(
    memory_id: RecordId, body: CorrectNoteRequest, repo: ScopedRepo
) -> CorrectionReceipt:
    try:
        receipt = correct_note(repo, memory_id, body.content, utc_now())
    except CorrectionError as error:
        repo.db.rollback()
        raise _changed(error) from error
    repo.db.commit()
    return receipt


@router.delete(
    "/notes/{memory_id}",
    response_model=DeletionReceipt,
    responses=_ERRORS,
    summary="Delete a note (and every version of it); nothing derived from it stays",
)
def delete_note_route(memory_id: RecordId, repo: ScopedRepo) -> DeletionReceipt:
    receipt = delete_note(repo, memory_id, utc_now())
    repo.db.commit()
    return receipt


@router.delete(
    "/hypotheses/{hypothesis_id}",
    response_model=DeletionReceipt,
    responses=_ERRORS,
    summary="Delete a tentative belief and anything that cited it",
)
def delete_hypothesis_route(hypothesis_id: RecordId, repo: ScopedRepo) -> DeletionReceipt:
    receipt = delete_hypothesis(repo, hypothesis_id, utc_now())
    repo.db.commit()
    return receipt
