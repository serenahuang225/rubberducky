import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.activity import ActivityLog, ActivityMiddleware
from app.api.demos import router as demos_router
from app.api.errors import ErrorEnvelope, install_error_handlers
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.media import router as media_router
from app.api.memory import router as memory_router
from app.api.pairing import router as pairing_router
from app.api.persona import router as persona_router
from app.api.scene import router as scene_router
from app.api.sessions import router as sessions_router
from app.api.tracing import router as tracing_router
from app.api.tutor import router as tutor_router
from app.api.voice import router as voice_router
from app.api.wait import router as wait_router
from app.clock import utc_now
from app.config import Settings, get_settings
from app.db.database import Database
from app.redaction import install_log_redaction, register_secrets
from app.tutor.cancellation import recover_pending_turns

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else get_settings()
    install_log_redaction()
    register_secrets(
        key.get_secret_value() if key is not None else None
        for key in (
            resolved.anthropic_api_key,
            resolved.tutor_endpoint_api_key,
            resolved.xai_api_key,
        )
    )
    # Creating the engine does not connect; the database is opened on first request.
    database = Database(resolved.database_url)
    activity_log = ActivityLog(resolved.tutor_activity_log_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            # Replies a previous process left pending can never arrive: say so honestly.
            recover_pending_turns(database, utc_now())
        except SQLAlchemyError:
            # An un-migrated database is reported by the routes (503), not by startup.
            logger.warning("Pending-turn recovery skipped: the database is not ready.")
        yield
        database.dispose()
        activity_log.close()

    application = FastAPI(title="Rubberducky tutor API", version=__version__, lifespan=lifespan)
    application.state.settings = resolved
    application.state.database = database
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        allow_credentials=False,
    )
    if resolved.tutor_activity_log_path:
        application.add_middleware(ActivityMiddleware, log=activity_log)
    install_error_handlers(application)
    application.include_router(health_router)
    application.include_router(demos_router)
    application.include_router(pairing_router)
    application.include_router(sessions_router)
    application.include_router(scene_router)
    application.include_router(graph_router)
    application.include_router(tracing_router)
    application.include_router(memory_router)
    application.include_router(tutor_router)
    application.include_router(persona_router)
    application.include_router(wait_router)
    application.include_router(media_router)
    application.include_router(voice_router)
    application.openapi = lambda: _openapi(application)  # type: ignore[method-assign]
    return application


def _openapi(application: FastAPI) -> dict[str, Any]:
    """Document the 422 body as the shared error envelope rather than FastAPI's default."""
    if application.openapi_schema is not None:
        return application.openapi_schema
    schema = get_openapi(
        title=application.title, version=application.version, routes=application.routes
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    envelope = ErrorEnvelope.model_json_schema(ref_template="#/components/schemas/{model}")
    for name, definition in envelope.pop("$defs", {}).items():
        components[name] = definition
    components["ErrorEnvelope"] = envelope
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            response = operation.get("responses", {}).get("422")
            if response is not None:
                response["description"] = "Request validation failed (error.v1 with fields)"
                response["content"] = {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
                }
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    application.openapi_schema = schema
    return schema


app = create_app()
