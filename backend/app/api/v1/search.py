"""POST /api/v1/search: retrieve previously captured page chunks by meaning."""

from fastapi import APIRouter, status

from app.api.deps import DbSession, EmbeddingEncoderDep
from app.api.errors import ErrorResponse
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search import semantic_search

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Semantic search over a user's stored page chunks (development stage, unauthenticated)",
    description=(
        "Encodes the query with the shared BGE encoder (`role=query`), then ranks that user's "
        "`PageChunkEmbedding` rows by pgvector cosine distance (`<=>`). Returns top-K **chunks** "
        "(not aggregated pages) with page metadata. `similarity` is defined as "
        "`1 - cosine_distance`. Empty result sets are `200` with `results: []`. "
        "`user_id` is a hard tenant filter; there is no authentication yet."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request (empty query, bad limit, bad UUID)"},
        503: {
            "model": ErrorResponse,
            "description": "Database or embedding encoder temporarily unavailable",
        },
    },
)
def search(
    payload: SearchRequest, session: DbSession, encoder: EmbeddingEncoderDep
) -> SearchResponse:
    """Return the top-K PageChunks whose stored passage embeddings are closest to the query.

    **Development-stage boundary, not an authenticated production endpoint.** The caller supplies
    `user_id` and nothing verifies who they are. Do not expose this service beyond a trusted
    machine or network.
    """
    return semantic_search(session, encoder, payload)
