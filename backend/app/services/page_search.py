"""Exact best-chunk page retrieval in one user-scoped query, with no relevance cutoff."""

import time

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.models import Page, PageChunk, PageChunkEmbedding
from app.schemas.page_search import PageSearchRequest, PageSearchResponse
from app.schemas.search import SearchResult
from app.schemas.lexical_search import LexicalSearchResult
from app.services.embeddings import EmbeddingEncoder
from app.services.search import _encode_query, _preview, require_encoder


def page_search(session: Session, encoder: EmbeddingEncoder | None,
                request: PageSearchRequest) -> PageSearchResponse:
    started = time.perf_counter()
    if request.mode == "semantic":
        encoder = require_encoder(encoder)
        vector = _encode_query(encoder, request.query)
        score = PageChunkEmbedding.embedding.cosine_distance(vector)
        source = (
            select(PageChunk.id.label("chunk_id"), score.label("score"))
            .select_from(PageChunkEmbedding)
            .join(PageChunk, (PageChunk.id == PageChunkEmbedding.page_chunk_id)
                  & (PageChunk.page_id == PageChunkEmbedding.page_id))
            .join(Page, (Page.id == PageChunkEmbedding.page_id)
                  & (Page.user_id == PageChunkEmbedding.user_id))
            .where(Page.user_id == request.user_id,
                   PageChunkEmbedding.user_id == request.user_id,
                   PageChunkEmbedding.embedding_model == encoder.model_id)
        )
        within_page = (score.asc(), PageChunk.chunk_index, PageChunk.id)
    else:
        config = literal_column("'english'::regconfig")
        document = func.to_tsvector(config, PageChunk.text)
        query = func.websearch_to_tsquery(config, request.query)
        score = func.ts_rank_cd(document, query)
        source = (
            select(PageChunk.id.label("chunk_id"), score.label("score"))
            .select_from(PageChunk).join(Page, Page.id == PageChunk.page_id)
            .where(Page.user_id == request.user_id, document.op("@@")(query))
        )
        within_page = (score.desc(), PageChunk.chunk_index, PageChunk.id)
    ranked = source.add_columns(
        func.row_number().over(partition_by=Page.id, order_by=within_page).label("page_position")
    ).subquery()
    order = ((ranked.c.score.asc(), Page.id, PageChunk.chunk_index, PageChunk.id)
             if request.mode == "semantic" else
             (ranked.c.score.desc(), Page.last_seen_at.desc(), Page.id,
              PageChunk.chunk_index, PageChunk.id))
    rows = session.execute(
        select(PageChunk, Page, ranked.c.score)
        .select_from(ranked).join(PageChunk, PageChunk.id == ranked.c.chunk_id)
        .join(Page, Page.id == PageChunk.page_id)
        .where(ranked.c.page_position == 1, Page.user_id == request.user_id)
        .order_by(*order).offset(request.offset).limit(request.limit + 1)
    ).all()
    results = []
    for chunk, page, value in rows[:request.limit]:
        fields = dict(chunk_id=chunk.id, page_id=page.id, canonical_url=page.canonical_url,
                      title=page.title, domain=page.domain, chunk_index=chunk.chunk_index,
                      text_preview=_preview(chunk.text), last_seen_at=page.last_seen_at)
        results.append(
            SearchResult(**fields, cosine_distance=float(value), similarity=1.0 - float(value))
            if request.mode == "semantic" else LexicalSearchResult(**fields, lexical_score=float(value))
        )
    return PageSearchResponse(
        query=request.query, mode=request.mode, limit=request.limit, offset=request.offset,
        result_count=len(results), results=results, truncated=len(rows) > request.limit,
        latency_ms=(time.perf_counter() - started) * 1000,
        result_state=("possible_matches" if results else "insufficient_evidence"
                      if request.mode == "semantic" else "no_sufficient_match"),
    )
