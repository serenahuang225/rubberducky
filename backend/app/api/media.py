"""Optional media routes: honest capabilities and bounded, learner-scoped media events.

Nothing here records raw media, creates evidence or changes a mastery estimate. See
``app.multimodal`` for the bounds and ``app.schemas.media`` for the contracts. Late events
(stale revision or cancellation epoch) are refused with 409 so they cannot restart speech,
drawings or memory effects.
"""

from fastapi import APIRouter

from app.api.deps import ScopedRepo, SettingsDep
from app.api.errors import ApiError, ErrorEnvelope
from app.api.sessions import SessionIdPath
from app.clock import utc_now
from app.multimodal.service import MediaEventError, capabilities, handle_media_event
from app.schemas.media import MediaCapabilities, MediaEventRequest, MediaEventResult

router = APIRouter(tags=["media"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    429: {"model": ErrorEnvelope},
}


@router.get(
    "/media/capabilities",
    response_model=MediaCapabilities,
    responses=_ERRORS,
    summary="What optional media can and cannot do here, with limits and disclosures",
)
def get_media_capabilities(_repo: ScopedRepo, settings: SettingsDep) -> MediaCapabilities:
    return capabilities(settings)


@router.post(
    "/sessions/{session_id}/media/events",
    response_model=MediaEventResult,
    responses=_ERRORS,
    summary="Submit one bounded media event (photo metadata, transcript update or weak cue)",
)
def post_media_event(
    session_id: SessionIdPath,
    body: MediaEventRequest,
    repo: ScopedRepo,
    settings: SettingsDep,
) -> MediaEventResult:
    try:
        result = handle_media_event(repo, settings, session_id, body, utc_now())
    except MediaEventError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    repo.db.commit()
    return result
