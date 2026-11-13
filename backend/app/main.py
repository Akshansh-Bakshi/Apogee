"""FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1 import router as api_v1_router
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory
from app.services.embeddings import create_embedding_encoder
from app.services.topics import TopicAssigner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_db_engine(app.state.settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # Built here so every request reuses the same encoder. Weights stay unloaded until first use.
    app.state.embedding_encoder = create_embedding_encoder(app.state.settings)
    app.state.topic_assigner = TopicAssigner(app.state.embedding_encoder)
    try:
        yield
    finally:
        engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(title="Apogee API", version=__version__, lifespan=lifespan)
    application.state.settings = settings or get_settings()
    application.include_router(api_v1_router)
    ui_dir = Path(__file__).resolve().parent / "ui"
    application.mount("/app/assets", StaticFiles(directory=ui_dir), name="app-assets")

    @application.get("/app", include_in_schema=False)
    def search_dashboard() -> FileResponse:
        return FileResponse(
            ui_dir / "index.html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
                ),
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    register_exception_handlers(application)
    return application
