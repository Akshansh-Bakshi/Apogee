"""POST /api/v1/search/lexical: PostgreSQL full-text retrieval baseline (B0)."""

from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.api.errors import ErrorResponse
from app.schemas.lexical_search import LexicalSearchRequest, LexicalSearchResponse
from app.services.lexical_search import lexical_search

router = APIRouter(tags=["lexical search"])


@router.post(
    "/search/lexical",
    response_model=LexicalSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Lexical search over a user's stored page chunks (B0 baseline)",
    description=(
        "Searches only PageChunk.text with PostgreSQL English full-text search, parsing the input "
        "with websearch_to_tsquery and ordering by ts_rank_cd (higher lexical_score first). "
        "Returns top-K chunks with page metadata. user_id is a hard tenant filter; there is no "
        "authentication yet. This endpoint is independent of semantic POST /search."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request (empty query, bad limit, bad UUID)"},
        503: {"model": ErrorResponse, "description": "Database temporarily unavailable"},
    },
)
def search_lexical(payload: LexicalSearchRequest, session: DbSession) -> LexicalSearchResponse:
    """Return ranked PageChunks using PostgreSQL's lexical matching and ranking."""
    return lexical_search(session, payload)
