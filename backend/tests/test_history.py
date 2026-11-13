"""Database-free history schema, aggregation, API, and tenant-scope tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_db_session
from app.main import create_app
from app.schemas.history import HistoryQuery
from app.schemas.topics import TopicAssignmentsResponse, TopicDefinition, TopicSuggestion
from app.services.history import assemble_history, get_user_history
from app.services.topic_taxonomy import TAXONOMY_VERSION, TOPICS
from tests.factories import make_settings

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


def assignments(*items: tuple[UUID, str | None]) -> TopicAssignmentsResponse:
    rows = [
        TopicSuggestion(
            page_id=page_id,
            status="suggested" if topic_id else "unclassified",
            topic_id=topic_id,
            similarity=0.7 if topic_id else None,
            reason=None if topic_id else "missing_embeddings",
            embedding_count=1 if topic_id else 0,
        )
        for page_id, topic_id in items
    ]
    return TopicAssignmentsResponse(
        taxonomy_version=TAXONOMY_VERSION,
        embedding_model="test/model",
        provisional_min_similarity=0.4,
        topics=[
            TopicDefinition(
                id=topic.id, name=topic.name, description=topic.description,
                prerequisites=list(topic.prerequisites),
            )
            for topic in TOPICS
        ],
        page_count=len(rows),
        suggested_count=sum(row.status == "suggested" for row in rows),
        unclassified_count=sum(row.status == "unclassified" for row in rows),
        assignments=rows,
    )


def event_row(
    *,
    event_id: UUID | None = None,
    page_id: UUID | None = None,
    occurred_at: datetime | None = NOW,
    title: str = "A stored page",
) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id or uuid4(), occurred_at=occurred_at, page_id=page_id,
        event_url="https://example.com/event", event_title=title,
        event_domain="example.com", page_canonical_url="https://example.com/page",
        page_title=title, page_domain="example.com",
    )


def test_deterministic_descending_order_and_stable_tie_breaker() -> None:
    page = uuid4()
    lower, higher = UUID(int=10), UUID(int=20)
    rows = [
        event_row(event_id=lower, page_id=page, occurred_at=NOW),
        event_row(event_id=uuid4(), page_id=page, occurred_at=NOW - timedelta(days=1)),
        event_row(event_id=higher, page_id=page, occurred_at=NOW),
    ]
    result = assemble_history(
        rows, assignments((page, "algorithms")),
        HistoryQuery(user_id=uuid4()), scan_truncated=False,
    )
    assert [item.event_id for item in result.events[:2]] == [higher, lower]
    assert result.events[-1].occurred_at == NOW - timedelta(days=1)


def test_limit_topic_filter_missing_embedding_and_invalid_timestamp() -> None:
    algorithm_page, missing_page = uuid4(), uuid4()
    rows = [
        event_row(page_id=algorithm_page),
        event_row(page_id=algorithm_page, occurred_at=NOW - timedelta(hours=1)),
        event_row(page_id=missing_page, occurred_at=NOW - timedelta(hours=2)),
        event_row(page_id=algorithm_page, occurred_at=None),
    ]
    filtered = assemble_history(
        rows, assignments((algorithm_page, "algorithms"), (missing_page, None)),
        HistoryQuery(user_id=uuid4(), topic_id="algorithms", limit=1),
        scan_truncated=False,
    )
    assert filtered.result_count == 1
    assert filtered.truncated is True
    assert filtered.omitted_invalid_timestamp_count == 1
    unfiltered = assemble_history(
        rows[:3], assignments((algorithm_page, "algorithms"), (missing_page, None)),
        HistoryQuery(user_id=uuid4()), scan_truncated=False,
    )
    missing = next(item for item in unfiltered.events if item.page_id == missing_page)
    assert missing.topic_status == "unclassified"
    assert missing.topic_reason == "missing_embeddings"
    assert missing.topic_cosine_similarity is None


def test_timezone_aware_range_and_topic_validation() -> None:
    with pytest.raises(ValidationError):
        HistoryQuery(user_id=uuid4(), start_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError, match="end_at"):
        HistoryQuery(user_id=uuid4(), start_at=NOW, end_at=NOW)
    with pytest.raises(ValidationError, match="topic_id"):
        HistoryQuery(user_id=uuid4(), topic_id="unknown")
    valid = HistoryQuery(
        user_id=uuid4(), start_at=NOW, end_at=NOW + timedelta(days=1),
    )
    assert valid.start_at == NOW


class Encoder:
    model_id = "test/model"
    dimension = 384

    def encode_batch(self, texts, *, role="passage"):
        output = []
        for index, _ in enumerate(texts):
            values = np.zeros(384)
            values[index] = 1
            output.append(values.tolist())
        return output


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.result_sets.pop(0))


def test_bounded_queries_scope_events_and_embeddings_to_user_and_page_subset() -> None:
    from app.services.topics import TopicAssigner

    user_id, page_id = uuid4(), uuid4()
    row = event_row(page_id=page_id)
    vector = np.zeros(384)
    vector[0] = 1
    session = FakeSession([[row], [(page_id, vector.tolist(), 384)]])
    result = get_user_history(
        session, TopicAssigner(Encoder()), HistoryQuery(user_id=user_id, limit=10),
    )
    assert result.result_count == 1
    assert result.events[0].provisional_topic_id == TOPICS[0].id
    assert len(session.statements) == 2
    event_sql = str(session.statements[0])
    embedding_sql = str(session.statements[1])
    assert "browsing_events.user_id =" in event_sql
    assert "pages.user_id =" in embedding_sql
    assert "page_chunk_embeddings.user_id =" in embedding_sql
    assert user_id in session.statements[0].compile().params.values()
    assert user_id in session.statements[1].compile().params.values()
    assert any(
        page_id in value
        for value in session.statements[1].compile().params.values()
        if isinstance(value, (list, tuple, set, frozenset))
    )


def test_date_boundaries_compile_as_inclusive_start_exclusive_end() -> None:
    from app.services.topics import TopicAssigner

    user_id = uuid4()
    session = FakeSession([[]])
    get_user_history(
        session,
        TopicAssigner(Encoder()),
        HistoryQuery(
            user_id=user_id, start_at=NOW, end_at=NOW + timedelta(days=1),
        ),
    )
    sql = str(session.statements[0])
    assert "browsing_events.occurred_at >=" in sql
    assert "browsing_events.occurred_at <" in sql


def test_empty_user_api_and_existing_routes_remain_available() -> None:
    app = create_app(make_settings())
    fake = FakeSession([[]])
    app.dependency_overrides[get_db_session] = lambda: fake
    with TestClient(app) as client:
        response = client.get(f"/api/v1/history?user_id={uuid4()}")
        invalid = client.get(f"/api/v1/history?user_id={uuid4()}&start_at=2026-01-01")
        schema = client.get("/openapi.json").json()["paths"]
    assert response.status_code == 200
    assert response.json()["events"] == []
    assert response.json()["result_count"] == 0
    assert invalid.status_code == 422
    assert {"/api/v1/search", "/api/v1/search/lexical", "/api/v1/topics/assignments",
            "/api/v1/topics/coverage", "/api/v1/history"} <= set(schema)
