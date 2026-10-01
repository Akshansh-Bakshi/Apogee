"""User-scoped PostgreSQL full-text retrieval over PageChunk.text (B0 baseline)."""

from __future__ import annotations

import logging
import time

from sqlalchemy import literal_column, select, func
from sqlalchemy.orm import Session

from app.models import Page, PageChunk
from app.schemas.lexical_search import (
    LexicalSearchRequest,
    LexicalSearchResponse,
    LexicalSearchResult,
)

logger = logging.getLogger(__name__)

TEXT_PREVIEW_MAX = 280


def _preview(text: str) -> str:
    if len(text) <= TEXT_PREVIEW_MAX:
        return text
    return text[: TEXT_PREVIEW_MAX - 1] + "…"


def lexical_search(session: Session, request: LexicalSearchRequest) -> LexicalSearchResponse:
    """Search only a user's chunk text with PostgreSQL websearch parsing and cover-density rank."""
    started = time.perf_counter()
    config = literal_column("'english'::regconfig")
    document = func.to_tsvector(config, PageChunk.text)
    tsquery = func.websearch_to_tsquery(config, request.query)
    rank = func.ts_rank_cd(document, tsquery).label("lexical_score")
    statement = (
        select(PageChunk, Page, rank)
        .join(Page, Page.id == PageChunk.page_id)
        .where(Page.user_id == request.user_id)
        .where(document.op("@@")(tsquery))
        .order_by(
            rank.desc(),
            Page.last_seen_at.desc(),
            PageChunk.page_id,
            PageChunk.chunk_index,
            PageChunk.id,
        )
        .limit(request.limit)
    )
    rows = session.execute(statement).all()
    results = [
        LexicalSearchResult(
            chunk_id=chunk.id,
            page_id=page.id,
            canonical_url=page.canonical_url,
            title=page.title,
            domain=page.domain,
            chunk_index=chunk.chunk_index,
            text_preview=_preview(chunk.text),
            last_seen_at=page.last_seen_at,
            lexical_score=float(lexical_score),
        )
        for chunk, page, lexical_score in rows
    ]
    latency_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "Lexical search for user %s returned %s hit(s) in %.1f ms",
        request.user_id,
        len(results),
        latency_ms,
    )
    return LexicalSearchResponse(
        query=request.query,
        limit=request.limit,
        result_count=len(results),
        latency_ms=latency_ms,
        results=results,
    )
