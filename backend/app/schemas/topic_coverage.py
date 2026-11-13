"""Typed, read-only exploration evidence and graph recommendations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TopicEvidence(BaseModel):
    topic_id: str
    name: str
    distinct_pages: int = Field(ge=0)
    visits: int = Field(ge=0)
    last_seen_at: datetime | None
    observed_subtopics: int = Field(ge=0)
    total_subtopics: int = Field(ge=0)
    activity_index: float = Field(ge=0, le=1)
    page_ids: list[UUID]
    mean_top_two_cosine_margin: float | None = Field(default=None, ge=0, le=2)


class TopicRecommendation(BaseModel):
    topic_id: str
    name: str
    relation: str = "prerequisite"
    source_topic_id: str
    source_topic_name: str
    source_distinct_pages: int = Field(ge=1)
    target_distinct_pages: int = Field(ge=0)
    target_visits: int = Field(ge=0)
    explanation: str
    source_page_ids: list[UUID]


class TopicCoverageResponse(BaseModel):
    taxonomy_version: str
    assignment_status: str = "provisional_zero_shot"
    score_kind: str = "observed_browsing_activity_not_mastery"
    as_of: datetime
    total_pages: int = Field(ge=0)
    assigned_pages: int = Field(ge=0)
    unclassified_pages: int = Field(ge=0)
    total_events: int = Field(ge=0)
    unassigned_events: int = Field(ge=0)
    populated_session_events: int = Field(ge=0)
    topics: list[TopicEvidence]
    recommendations: list[TopicRecommendation]
    recommendation_status: str
