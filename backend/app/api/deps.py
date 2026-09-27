"""FastAPI dependencies. State lives on ``app.state`` (set in the lifespan), not in module globals."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.embeddings import EmbeddingEncoder
from app.services.search import require_encoder


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_embedding_encoder(request: Request) -> EmbeddingEncoder:
    encoder = getattr(request.app.state, "embedding_encoder", None)
    return require_encoder(encoder)


AppSettings = Annotated[Settings, Depends(get_app_settings)]
DbSession = Annotated[Session, Depends(get_db_session)]
EmbeddingEncoderDep = Annotated[EmbeddingEncoder, Depends(get_embedding_encoder)]
