"""Current observation inference; synthetic scores are not calibrated usefulness."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from app.schemas.topic_coverage import TopicRecommendation


class RankedTopic(BaseModel):
    topic_id: str
    rank: int = Field(ge=1, le=8)
    expected_synthetic_grade: float = Field(ge=0, le=2)
    evidence: dict[str, int | float | str | bool | None]
    explanation: str


class ModelRecommendations(BaseModel):
    source: Literal['model', 'rule_based']
    fallback_reason: str | None = None
    as_of: datetime
    taxonomy_version: str
    feature_schema_version: str
    feature_provenance: str = 'Current provisional assignments; owned events occurred and stored by as_of; no historical reconstruction'
    training_provenance: str = 'SYNTHETIC rubric imitation; no real recommendation feedback or new independent test evaluation'
    score_kind: str = 'expected_synthetic_grade_not_calibrated_usefulness_or_mastery'
    model_version: str | None = None
    assigned_pages: int = Field(ge=0)
    unclassified_pages: int = Field(ge=0)
    eligible_events: int = Field(ge=0)
    ranking: list[RankedTopic] = Field(default_factory=list, max_length=8)
    rule_recommendations: list[TopicRecommendation]
