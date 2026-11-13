"""Read-only, provisional topic assignment contract."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TopicSimilarityEvidence(BaseModel):
    """One ranked cosine comparison. Similarity is neither confidence nor probability."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    topic_id: str
    cosine_similarity: float = Field(ge=-1, le=1)


class TopicSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: UUID
    status: str = Field(pattern="^(suggested|unclassified)$")
    topic_id: str | None
    similarity: float | None = Field(default=None, ge=-1, le=1)
    reason: str | None = None
    embedding_count: int = Field(ge=0)
    # Optional for wire compatibility with Stage A clients and stored fixtures.
    evidence_status: str | None = Field(default=None, pattern="^(available|unavailable)$")
    evidence_unavailable_reason: str | None = None
    top_topic_id: str | None = None
    top_cosine_similarity: float | None = Field(default=None, ge=-1, le=1)
    runner_up_topic_id: str | None = None
    runner_up_cosine_similarity: float | None = Field(default=None, ge=-1, le=1)
    top_two_cosine_margin: float | None = Field(default=None, ge=0, le=2)
    topic_similarities: list[TopicSimilarityEvidence] | None = None

    @model_validator(mode="after")
    def consistent(self) -> "TopicSuggestion":
        if self.status == "suggested" and (self.topic_id is None or self.similarity is None or self.reason is not None):
            raise ValueError("suggested topics require an ID and similarity")
        if self.status == "unclassified" and (self.topic_id is not None or self.similarity is not None or self.reason is None):
            raise ValueError("unclassified pages require a reason and no score")
        if self.evidence_status == "available":
            if (
                self.evidence_unavailable_reason is not None
                or self.top_topic_id is None
                or self.top_cosine_similarity is None
                or self.runner_up_topic_id is None
                or self.runner_up_cosine_similarity is None
                or self.top_two_cosine_margin is None
                or not self.topic_similarities
                or len(self.topic_similarities) < 2
            ):
                raise ValueError("available evidence requires ranked top-two and topic similarities")
            expected_ranks = list(range(1, len(self.topic_similarities) + 1))
            if [item.rank for item in self.topic_similarities] != expected_ranks:
                raise ValueError("topic similarity ranks must be consecutive")
            if len({item.topic_id for item in self.topic_similarities}) != len(self.topic_similarities):
                raise ValueError("topic similarity IDs must be unique")
            if (
                self.topic_similarities[0].topic_id != self.top_topic_id
                or self.topic_similarities[0].cosine_similarity != self.top_cosine_similarity
                or self.topic_similarities[1].topic_id != self.runner_up_topic_id
                or self.topic_similarities[1].cosine_similarity != self.runner_up_cosine_similarity
            ):
                raise ValueError("top-two fields must match ranked topic similarities")
            if abs(
                self.top_two_cosine_margin
                - (self.top_cosine_similarity - self.runner_up_cosine_similarity)
            ) > 1e-12:
                raise ValueError("top-two margin must equal the similarity difference")
            if self.status == "suggested" and (
                self.topic_id != self.top_topic_id or self.similarity != self.top_cosine_similarity
            ):
                raise ValueError("suggested assignment must match top-ranked evidence")
        elif self.evidence_status == "unavailable":
            if (
                not self.evidence_unavailable_reason
                or self.top_topic_id is not None
                or self.top_cosine_similarity is not None
                or self.runner_up_topic_id is not None
                or self.runner_up_cosine_similarity is not None
                or self.top_two_cosine_margin is not None
                or self.topic_similarities is not None
            ):
                raise ValueError("unavailable evidence requires only an unavailable reason")
        elif any(
            value is not None
            for value in (
                self.evidence_unavailable_reason,
                self.top_topic_id,
                self.top_cosine_similarity,
                self.runner_up_topic_id,
                self.runner_up_cosine_similarity,
                self.top_two_cosine_margin,
                self.topic_similarities,
            )
        ):
            raise ValueError("evidence fields require an evidence_status")
        return self


class TopicDefinition(BaseModel):
    id: str
    name: str
    description: str
    prerequisites: list[str]


class TopicAssignmentsResponse(BaseModel):
    taxonomy_version: str
    embedding_model: str
    similarity_kind: str = "cosine_similarity_not_probability"
    threshold_status: str = "provisional_uncalibrated"
    provisional_min_similarity: float
    topics: list[TopicDefinition]
    page_count: int
    suggested_count: int
    unclassified_count: int
    assignments: list[TopicSuggestion]
