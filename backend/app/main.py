import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.errors import install_error_handlers
from app.api.graph import router as graph_router
from app.api.health import router as health_router
from app.api.memory import router as memory_router
from app.api.pairing import router as pairing_router
from app.api.persona import router as persona_router
from app.api.scene import router as scene_router
from app.api.sessions import router as sessions_router
from app.api.tracing import router as tracing_router
from app.api.tutor import router as tutor_router
from app.api.wait import router as wait_router
from app.clock import utc_now
from app.config import Settings, get_settings
from app.db.database import Database
from app.tutor.cancellation import recover_pending_turns

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else get_settings()
    # Creating the engine does not connect; the database is opened on first request.
    database = Database(resolved.database_url)

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
    install_error_handlers(application)
    application.include_router(health_router)
    application.include_router(pairing_router)
    application.include_router(sessions_router)
    application.include_router(scene_router)
    application.include_router(graph_router)
    application.include_router(tracing_router)
    application.include_router(memory_router)
    application.include_router(tutor_router)
    application.include_router(persona_router)
    application.include_router(wait_router)
    return application


app = create_app()
