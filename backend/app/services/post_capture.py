"""Best-effort embedding work scheduled after a page capture commits."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import PageChunk
from app.services.embeddings import EmbeddingEncoder, embed_page_chunks

logger = logging.getLogger(__name__)


def embed_page_after_capture(
    session_factory: sessionmaker[Session], page_id: uuid.UUID, encoder: EmbeddingEncoder
) -> None:
    """Embed the page's current chunks in an independent transaction.

    Failures are isolated from the already-committed capture and logged without exception details,
    which could contain page text from a model or database error.
    """
    try:
        with session_factory() as session:
            chunk_ids = session.scalars(
                select(PageChunk.id)
                .where(PageChunk.page_id == page_id)
                .order_by(PageChunk.chunk_index)
            ).all()
            if chunk_ids:
                embed_page_chunks(session, chunk_ids, encoder)
            session.commit()
    except Exception:
        logger.error("Post-capture embedding failed for page_id=%s", page_id)

