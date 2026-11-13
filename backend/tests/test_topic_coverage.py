"""Database-free tests for exploration evidence and prerequisite explanations."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db_session
from app.main import create_app
from app.schemas.topics import (
    TopicAssignmentsResponse, TopicDefinition, TopicSimilarityEvidence, TopicSuggestion,
)
from app.services.topic_coverage import activity_index, build_coverage, recommendations
from app.services.topic_taxonomy import TAXONOMY_VERSION, TOPICS, Topic
from tests.factories import make_settings

NOW = datetime(2026, 11, 12, tzinfo=UTC)


def assignments(*items: tuple) -> TopicAssignmentsResponse:
    rows = [
        TopicSuggestion(
            page_id=page_id, status="suggested" if topic_id else "unclassified",
            topic_id=topic_id, similarity=0.6 if topic_id else None,
            reason=None if topic_id else "missing_embeddings",
            embedding_count=1 if topic_id else 0,
        )
        for page_id, topic_id in items
    ]
    return TopicAssignmentsResponse(
        taxonomy_version=TAXONOMY_VERSION, embedding_model="test/model",
        provisional_min_similarity=0.4,
        topics=[TopicDefinition(id=t.id, name=t.name, description=t.description,
                                prerequisites=list(t.prerequisites)) for t in TOPICS],
        page_count=len(rows), suggested_count=sum(x.status == "suggested" for x in rows),
        unclassified_count=sum(x.status == "unclassified" for x in rows), assignments=rows,
    )


def test_distinct_pages_do_not_increase_on_repeat_visits() -> None:
    a, b, missing = uuid4(), uuid4(), uuid4()
    data = build_coverage(
        assignments((a, "algorithms"), (b, "algorithms"), (missing, None)),
        [(a, NOW - timedelta(days=3), None), (a, NOW - timedelta(days=1), None),
         (b, NOW, None), (missing, NOW, None), (None, NOW, None)],
        TOPICS, NOW,
    )
    algorithms = next(x for x in data.topics if x.topic_id == "algorithms")
    assert (algorithms.distinct_pages, algorithms.visits, algorithms.last_seen_at) == (2, 3, NOW)
    assert data.unclassified_pages == 1
    assert (data.total_events, data.unassigned_events, data.populated_session_events) == (5, 2, 0)
    assert next(x for x in data.topics if x.topic_id == "programming").distinct_pages == 0


def test_coverage_reuses_assignment_margins_without_changing_counts() -> None:
    page_id = uuid4()
    result = assignments((page_id, "algorithms"))
    result.assignments[0] = TopicSuggestion(
        page_id=page_id, status="suggested", topic_id="algorithms", similarity=0.7,
        embedding_count=2, evidence_status="available",
        top_topic_id="algorithms", top_cosine_similarity=0.7,
        runner_up_topic_id="information-retrieval", runner_up_cosine_similarity=0.5,
        top_two_cosine_margin=0.2,
        topic_similarities=[
            TopicSimilarityEvidence(rank=1, topic_id="algorithms", cosine_similarity=0.7),
            TopicSimilarityEvidence(rank=2, topic_id="information-retrieval", cosine_similarity=0.5),
        ],
    )
    data = build_coverage(result, [(page_id, NOW, None)], TOPICS, NOW)
    algorithms = next(item for item in data.topics if item.topic_id == "algorithms")
    assert algorithms.mean_top_two_cosine_margin == 0.2
    assert (algorithms.distinct_pages, algorithms.visits) == (1, 1)


def test_activity_index_normalization_and_recency_boundaries() -> None:
    assert activity_index(0, 0, None, 0, 0, NOW) == 0
    recent = activity_index(1, 1, NOW, 0, 0, NOW)
    old = activity_index(1, 1, NOW - timedelta(days=30), 0, 0, NOW)
    assert recent > old
    assert activity_index(1, 1, NOW + timedelta(days=1), 0, 0, NOW) == recent
    assert activity_index(50, 50, NOW, 1, 1, NOW) == 1.0
    with pytest.raises(ValueError):
        activity_index(1, 1, datetime(2026, 1, 1), 0, 0, NOW)


def test_subtopic_breadth_and_deduplicated_graph_recommendations() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    data = build_coverage(
        assignments((a, "algorithms"), (b, "web-development"), (c, "information-retrieval")),
        [(a, NOW, None), (b, NOW, None), (c, NOW, None)], TOPICS, NOW,
    )
    programming = next(x for x in data.topics if x.topic_id == "programming")
    assert (programming.observed_subtopics, programming.total_subtopics) == (2, 2)
    assert [x.topic_id for x in data.recommendations] == ["databases", "programming"]
    assert len({x.topic_id for x in data.recommendations}) == 2
    assert all("captured pages" in x.explanation and "not a knowledge gap" in x.explanation
               for x in data.recommendations)
    assert next(x for x in data.recommendations if x.topic_id == "programming").source_topic_id == "algorithms"


def test_no_evidence_and_cycle_rejection() -> None:
    data = build_coverage(assignments(), [], TOPICS, NOW)
    assert data.recommendations == []
    assert data.recommendation_status == "insufficient_evidence"
    assert data.total_pages == data.total_events == 0
    assert all(x.activity_index == 0 for x in data.topics)
    cyclic = (Topic("a", "A", "a", ("b",)), Topic("b", "B", "b", ("a",)))
    with pytest.raises(ValueError, match="cyclic"):
        recommendations([], cyclic)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult([])


def test_endpoint_empty_user_and_both_queries_scoped() -> None:
    app = create_app(make_settings())
    fake = FakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake
    user_id = uuid4()
    with TestClient(app) as client:
        assert client.get("/api/v1/topics/coverage?user_id=invalid").status_code == 422
        response = client.get(f"/api/v1/topics/coverage?user_id={user_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["total_pages"] == body["total_events"] == 0
    assert body["recommendation_status"] == "insufficient_evidence"
    assert len(fake.statements) == 2
    for statement in fake.statements:
        assert user_id in statement.compile().params.values()
    assert "browsing_events.user_id =" in str(fake.statements[1])
