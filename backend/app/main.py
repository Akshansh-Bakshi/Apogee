"""FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory
from app.services.embeddings import create_embedding_encoder


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_db_engine(app.state.settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # Built here so every request reuses the same encoder. Weights stay unloaded until first use.
    app.state.embedding_encoder = create_embedding_encoder(app.state.settings)
    try:
        yield
    finally:
        engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(title="Apogee API", version=__version__, lifespan=lifespan)
    application.state.settings = settings or get_settings()
    application.include_router(api_v1_router)
    register_exception_handlers(application)
    return application
