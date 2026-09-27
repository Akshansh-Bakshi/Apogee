"""API contract for POST /api/v1/search. Separate from the ORM models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUERY_LENGTH = 1000
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


class SearchRequest(BaseModel):
    """One natural-language recollection query, scoped to a single user.

    Only these fields are accepted. ``extra="forbid"`` rejects unknown keys instead of ignoring
    them. ``user_id`` is the development-stage identity already used by capture; there is no
    authentication yet.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID = Field(description="Owner whose stored chunk embeddings may be searched.")
    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="Natural-language recollection. Surrounding whitespace is stripped.",
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Maximum number of PageChunk hits to return (top-K). Default 10, maximum 50.",
    )

    @field_validator("query", mode="before")
    @classmethod
    def _query_must_be_non_empty(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped


class SearchResult(BaseModel):
    """One retrieved PageChunk plus the page metadata the UI/evaluation layer needs."""

    chunk_id: UUID
    page_id: UUID
    canonical_url: str
    title: str | None
    domain: str
    chunk_index: int
    text_preview: str = Field(description="Truncated chunk text; not the full stored passage.")
    last_seen_at: datetime = Field(description="The owning page's last_seen_at timestamp.")
    cosine_distance: float = Field(
        description="pgvector cosine distance (<=>). Lower is closer. Preserved for evaluation."
    )
    similarity: float = Field(
        description="Defined as 1 - cosine_distance. Not an independent ranking score."
    )


class SearchResponse(BaseModel):
    query: str = Field(description="The normalised (stripped) query that was encoded.")
    limit: int
    result_count: int
    latency_ms: float = Field(description="Encoder + database time for this request, in milliseconds.")
    results: list[SearchResult]
