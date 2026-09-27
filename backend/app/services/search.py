"""User-scoped semantic retrieval over stored PageChunk embeddings.

The route stays thin: this module encodes the query with the shared encoder and runs the pgvector
cosine search. It does not commit; search is read-only. Callers own the SQLAlchemy session.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Page, PageChunk, PageChunkEmbedding
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.services.embeddings import EmbeddingEncoder

logger = logging.getLogger(__name__)

TEXT_PREVIEW_MAX = 280


class SearchError(Exception):
    """Expected search failures. Messages are safe to show to clients."""


class EncoderUnavailableError(SearchError):
    """The process has no usable embedding encoder (missing from app.state, or encode failed)."""


def _preview(text: str) -> str:
    if len(text) <= TEXT_PREVIEW_MAX:
        return text
    return text[: TEXT_PREVIEW_MAX - 1] + "…"


def semantic_search(
    session: Session, encoder: EmbeddingEncoder, request: SearchRequest
) -> SearchResponse:
    """Encode ``request.query`` as a BGE query vector and return the top-K chunks for that user."""
    started = time.perf_counter()
    query_vector = _encode_query(encoder, request.query)
    distance = PageChunkEmbedding.embedding.cosine_distance(query_vector)
    statement = (
        select(PageChunk, Page, distance.label("cosine_distance"))
        .select_from(PageChunkEmbedding)
        .join(
            PageChunk,
            (PageChunk.id == PageChunkEmbedding.page_chunk_id)
            & (PageChunk.page_id == PageChunkEmbedding.page_id),
        )
        .join(
            Page,
            (Page.id == PageChunkEmbedding.page_id)
            & (Page.user_id == PageChunkEmbedding.user_id),
        )
        .where(PageChunkEmbedding.user_id == request.user_id)
        .where(PageChunkEmbedding.embedding_model == encoder.model_id)
        .order_by(distance)
        .limit(request.limit)
    )
    rows = session.execute(statement).all()
    results = [
        SearchResult(
            chunk_id=chunk.id,
            page_id=page.id,
            canonical_url=page.canonical_url,
            title=page.title,
            domain=page.domain,
            chunk_index=chunk.chunk_index,
            text_preview=_preview(chunk.text),
            last_seen_at=page.last_seen_at,
            cosine_distance=float(cosine_distance),
            similarity=1.0 - float(cosine_distance),
        )
        for chunk, page, cosine_distance in rows
    ]
    latency_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "Semantic search for user %s returned %s hit(s) in %.1f ms",
        request.user_id,
        len(results),
        latency_ms,
    )
    return SearchResponse(
        query=request.query,
        limit=request.limit,
        result_count=len(results),
        latency_ms=latency_ms,
        results=results,
    )


def _encode_query(encoder: EmbeddingEncoder, query: str) -> list[float]:
    try:
        return encoder.encode_text(query, role="query")
    except EncoderUnavailableError:
        raise
    except Exception:
        logger.exception("Query encoding failed")
        raise EncoderUnavailableError("The embedding encoder is unavailable.") from None


def require_encoder(encoder: EmbeddingEncoder | None) -> EmbeddingEncoder:
    """Raise if lifespan did not attach an encoder (or a test cleared app.state)."""
    if encoder is None:
        raise EncoderUnavailableError("The embedding encoder is unavailable.")
    return encoder
