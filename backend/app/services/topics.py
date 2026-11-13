"""Provisional zero-shot topics from existing passage embeddings; never writes to the database."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from uuid import UUID

import numpy as np
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Page, PageChunkEmbedding
from app.models.page_chunk_embedding import EMBEDDING_DIMENSION
from app.schemas.topics import (
    TopicAssignmentsResponse,
    TopicDefinition,
    TopicSimilarityEvidence,
    TopicSuggestion,
)
from app.services.embeddings import EmbeddingEncoder
from app.services.search import EncoderUnavailableError
from app.services.topic_taxonomy import TAXONOMY_VERSION, TOPICS, Topic

DEFAULT_PROVISIONAL_MIN_SIMILARITY = 0.40  # uncalibrated; human topic review required


def unit_vector(value: object) -> np.ndarray:
    """Reject missing, malformed, non-finite, and zero vectors before cosine comparison."""
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid vector") from exc
    if vector.shape != (EMBEDDING_DIMENSION,) or not np.isfinite(vector).all():
        raise ValueError("invalid vector shape or values")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError("zero or invalid vector")
    return vector / norm


def page_vector(vectors: list[object]) -> np.ndarray:
    """Equal-weight mean of ordered, individually normalized chunks; normalize the mean."""
    if not vectors:
        raise ValueError("no embeddings")
    mean = np.mean([unit_vector(vector) for vector in vectors], axis=0)
    return unit_vector(mean)


class TopicAssigner:
    def __init__(
        self,
        encoder: EmbeddingEncoder,
        *,
        topics: tuple[Topic, ...] = TOPICS,
        min_similarity: float = DEFAULT_PROVISIONAL_MIN_SIMILARITY,
    ) -> None:
        if not -1 <= min_similarity <= 1:
            raise ValueError("min_similarity must be between -1 and 1")
        if len(topics) < 2 or len({topic.id for topic in topics}) != len(topics):
            raise ValueError("topics must contain at least two unique IDs")
        self.encoder = encoder
        self.topics = topics
        self.min_similarity = min_similarity
        self._topic_vectors: tuple[np.ndarray, ...] | None = None
        self._lock = Lock()

    def _prototypes(self) -> tuple[np.ndarray, ...]:
        # One cache per app/encoder. Lock also prevents concurrent requests loading weights twice.
        with self._lock:
            if self._topic_vectors is None:
                try:
                    vectors = self.encoder.encode_batch(
                        [topic.description for topic in self.topics], role="query"
                    )
                    if len(vectors) != len(self.topics):
                        raise ValueError("incorrect topic vector count")
                    self._topic_vectors = tuple(unit_vector(vector) for vector in vectors)
                except Exception:
                    raise EncoderUnavailableError("The embedding encoder is unavailable.") from None
            return self._topic_vectors

    def suggest(self, page_id: UUID, vectors: list[object]) -> TopicSuggestion:
        if not vectors:
            return TopicSuggestion(page_id=page_id, status="unclassified", topic_id=None,
                                   reason="missing_embeddings", embedding_count=0,
                                   evidence_status="unavailable",
                                   evidence_unavailable_reason="missing_embeddings")
        try:
            vector = page_vector(vectors)
        except ValueError:
            return TopicSuggestion(page_id=page_id, status="unclassified", topic_id=None,
                                   reason="invalid_embeddings", embedding_count=len(vectors),
                                   evidence_status="unavailable",
                                   evidence_unavailable_reason="invalid_embeddings")
        candidates = [
            (float(np.dot(vector, prototype)), topic.id)
            for topic, prototype in zip(self.topics, self._prototypes(), strict=True)
        ]
        # This is the original Stage A ordering: descending raw cosine, then topic ID.
        ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
        score, topic_id = ranked[0]
        score = max(-1.0, min(1.0, score))  # avoid floating-point boundary drift
        runner_score, runner_topic_id = ranked[1]
        runner_score = max(-1.0, min(1.0, runner_score))
        ranked_evidence = [
            TopicSimilarityEvidence(
                rank=rank,
                topic_id=candidate_topic_id,
                cosine_similarity=max(-1.0, min(1.0, candidate_score)),
            )
            for rank, (candidate_score, candidate_topic_id) in enumerate(ranked, start=1)
        ]
        evidence = {
            "evidence_status": "available",
            "top_topic_id": topic_id,
            "top_cosine_similarity": score,
            "runner_up_topic_id": runner_topic_id,
            "runner_up_cosine_similarity": runner_score,
            "top_two_cosine_margin": max(0.0, score - runner_score),
            "topic_similarities": ranked_evidence,
        }
        if score < self.min_similarity:
            return TopicSuggestion(page_id=page_id, status="unclassified", topic_id=None,
                                   reason="below_provisional_threshold", embedding_count=len(vectors),
                                   **evidence)
        return TopicSuggestion(page_id=page_id, status="suggested", topic_id=topic_id,
                               similarity=score, embedding_count=len(vectors), **evidence)


def assign_user_pages(
    session: Session,
    user_id: UUID,
    assigner: TopicAssigner,
    *,
    page_ids: set[UUID] | None = None,
) -> TopicAssignmentsResponse:
    """One scoped read of all pages, or a bounded requested subset, plus current-model embeddings."""
    embedding = PageChunkEmbedding
    statement = (
        select(Page.id, embedding.embedding, embedding.embedding_dimension)
        .select_from(Page)
        .outerjoin(
            embedding,
            and_(
                embedding.page_id == Page.id,
                embedding.user_id == user_id,
                embedding.embedding_model == assigner.encoder.model_id,
            ),
        )
        .where(Page.user_id == user_id)
        .order_by(Page.id, embedding.page_chunk_id)
    )
    if page_ids is not None:
        if not page_ids:
            rows = []
        else:
            statement = statement.where(Page.id.in_(page_ids))
            rows = session.execute(statement).all()
    else:
        rows = session.execute(statement).all()
    by_page: dict[UUID, list[object]] = defaultdict(list)
    for page_id, vector, dimension in rows:
        by_page[page_id]  # include pages with no embedding
        if vector is not None:
            by_page[page_id].append(vector if dimension == EMBEDDING_DIMENSION else None)
    assignments = [assigner.suggest(page_id, vectors) for page_id, vectors in by_page.items()]
    suggested = sum(item.status == "suggested" for item in assignments)
    return TopicAssignmentsResponse(
        taxonomy_version=TAXONOMY_VERSION,
        embedding_model=assigner.encoder.model_id,
        provisional_min_similarity=assigner.min_similarity,
        topics=[TopicDefinition(id=t.id, name=t.name, description=t.description,
                                prerequisites=list(t.prerequisites)) for t in assigner.topics],
        page_count=len(assignments),
        suggested_count=suggested,
        unclassified_count=len(assignments) - suggested,
        assignments=assignments,
    )
