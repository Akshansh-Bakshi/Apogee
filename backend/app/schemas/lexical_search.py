"""API contract for the independent PostgreSQL full-text retrieval baseline."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.search import DEFAULT_LIMIT, MAX_LIMIT, MAX_QUERY_LENGTH


class LexicalSearchRequest(BaseModel):
    """Natural-language query against one user's stored PageChunk text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID = Field(description="Owner whose stored page chunks may be searched.")
    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="Natural-language query parsed by PostgreSQL websearch_to_tsquery.",
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Maximum number of PageChunk hits to return. Default 10, maximum 50.",
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


class LexicalSearchResult(BaseModel):
    """One chunk hit with a PostgreSQL lexical rank (higher values rank first)."""

    chunk_id: UUID
    page_id: UUID
    canonical_url: str
    title: str | None
    domain: str
    chunk_index: int
    text_preview: str = Field(description="Truncated chunk text; not the full stored passage.")
    last_seen_at: datetime = Field(description="The owning page's last_seen_at timestamp.")
    lexical_score: float = Field(
        description="PostgreSQL ts_rank_cd score over PageChunk.text; higher ranks first."
    )


class LexicalSearchResponse(BaseModel):
    query: str = Field(description="The normalised (stripped) query sent to PostgreSQL FTS.")
    limit: int
    result_count: int
    latency_ms: float = Field(description="Database search time for this request, in milliseconds.")
    results: list[LexicalSearchResult]
