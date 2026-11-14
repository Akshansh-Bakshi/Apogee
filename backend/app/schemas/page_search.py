"""Page retrieval contract; existing chunk contracts remain independent."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.search import SearchRequest, SearchResult
from app.schemas.lexical_search import LexicalSearchResult


class PageSearchRequest(SearchRequest):
    mode: Literal["semantic", "lexical"] = "semantic"
    limit: int = Field(default=10, ge=1, le=50, description="Maximum distinct pages (1–50).")
    offset: int = Field(default=0, ge=0, le=49, description="Zero-based page offset within the first 50 results.")

    @model_validator(mode="after")
    def validate_result_window(self) -> "PageSearchRequest":
        if self.offset + self.limit > 50:
            raise ValueError("offset plus limit must not exceed 50")
        return self


class PageSearchResponse(BaseModel):
    query: str
    mode: Literal["semantic", "lexical"]
    limit: int
    offset: int = 0
    result_count: int
    latency_ms: float
    results: list[SearchResult | LexicalSearchResult]
    result_state: Literal["possible_matches", "no_sufficient_match", "insufficient_evidence"]
    truncated: bool
    result_unit: Literal["page"] = "page"
