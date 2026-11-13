"""Read-only browsing-event timeline contract."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.topic_taxonomy import TOPICS

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 100


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    topic_id: str | None = None
    limit: int = Field(default=DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT)

    @field_validator("topic_id")
    @classmethod
    def valid_topic(cls, value: str | None) -> str | None:
        if value is not None and value not in {topic.id for topic in TOPICS}:
            raise ValueError("topic_id must belong to the frozen taxonomy")
        return value

    @model_validator(mode="after")
    def valid_range(self) -> "HistoryQuery":
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class HistoryTopicOption(BaseModel):
    id: str
    name: str


class HistoryEvent(BaseModel):
    event_id: UUID
    occurred_at: datetime
    page_id: UUID | None
    canonical_url: str
    title: str | None
    domain: str
    topic_status: Literal["suggested", "unclassified", "unavailable"]
    provisional_topic_id: str | None = None
    topic_cosine_similarity: float | None = Field(default=None, ge=-1, le=1)
    top_two_cosine_margin: float | None = Field(default=None, ge=0, le=2)
    topic_reason: str | None = None


class HistoryResponse(BaseModel):
    taxonomy_version: str
    assignment_status: str = "provisional_zero_shot"
    timestamp_semantics: str = "recorded_event_instant"
    order: str = "occurred_at_desc_event_id_desc"
    start_at: datetime | None
    end_at: datetime | None
    topic_filter: str | None
    limit: int
    candidate_event_count: int = Field(ge=0)
    result_count: int = Field(ge=0)
    omitted_invalid_timestamp_count: int = Field(ge=0)
    truncated: bool
    topics: list[HistoryTopicOption]
    events: list[HistoryEvent]
