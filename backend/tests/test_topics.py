"""Database-free checks for provisional topic assignment and scoped query construction."""

import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_db_session
from app.main import create_app
from app.schemas.topics import TopicSuggestion
from app.services.topic_taxonomy import TAXONOMY_VERSION, Topic
from app.services.topics import TopicAssigner, assign_user_pages, page_vector, unit_vector
from tests.factories import make_settings


def vector(x: float, y: float = 0) -> list[float]:
    values = np.zeros(384)
    values[0], values[1] = x, y
    return values.tolist()


class Encoder:
    model_id = "test/model-v1"
    dimension = 384

    def __init__(self) -> None:
        self.calls = []

    def encode_batch(self, texts, *, role="passage"):
        self.calls.append((tuple(texts), role))
        return [vector(1, 0), vector(0, 1)]


TOPICS = (
    Topic("a", "Alpha", "A general topic about alpha."),
    Topic("b", "Beta", "A general topic about beta."),
)


def test_normalization_and_equal_weight_page_mean() -> None:
    assert unit_vector(vector(3))[0] == pytest.approx(1)
    combined = page_vector([vector(10), vector(0, 1)])
    assert combined[0] == pytest.approx(2**-0.5)
    assert combined[1] == pytest.approx(2**-0.5)
    for invalid in ([], [0] * 384, [float("nan")] * 384, [1] * 383):
        with pytest.raises(ValueError):
            unit_vector(invalid)
    with pytest.raises(ValueError):
        page_vector([vector(1), vector(-1)])


def test_missing_invalid_threshold_and_deterministic_tie() -> None:
    encoder = Encoder()
    assigner = TopicAssigner(encoder, topics=TOPICS, min_similarity=0.8)
    pid = uuid.uuid4()
    missing = assigner.suggest(pid, [])
    assert missing.reason == "missing_embeddings"
    assert missing.evidence_status == "unavailable"
    assert missing.topic_similarities is None
    invalid = assigner.suggest(pid, [[float("nan")] * 384])
    assert invalid.reason == "invalid_embeddings"
    assert invalid.evidence_status == "unavailable"
    below = assigner.suggest(pid, [vector(1, 1)])
    assert below.reason == "below_provisional_threshold"
    assert below.evidence_status == "available"
    assert below.top_topic_id == "a"
    assert below.topic_id is None  # the original cutoff outcome remains unchanged
    hit = assigner.suggest(pid, [vector(1)])
    assert (hit.status, hit.topic_id, hit.similarity) == ("suggested", "a", 1.0)
    assert (hit.top_topic_id, hit.runner_up_topic_id) == ("a", "b")
    tie = TopicAssigner(encoder, topics=TOPICS, min_similarity=0).suggest(pid, [vector(1, 1)])
    assert tie.topic_id == "a"
    assert tie.runner_up_topic_id == "b"
    assert tie.top_two_cosine_margin == pytest.approx(0)
    assert [item.topic_id for item in tie.topic_similarities] == ["a", "b"]
    assert encoder.calls == [(tuple(t.description for t in TOPICS), "query")] * 2


class ManyTopicEncoder:
    model_id = MODEL_ID = "test/model-many"
    dimension = 384

    def encode_batch(self, texts, *, role="passage"):
        output = []
        for index, _ in enumerate(texts):
            values = np.zeros(384)
            values[index] = 1
            output.append(values.tolist())
        return output


def test_all_eight_similarities_are_ranked_deterministically() -> None:
    topics = tuple(
        Topic(topic_id, topic_id.upper(), f"General description {topic_id}.")
        for topic_id in ("h", "g", "f", "e", "d", "c", "b", "a")
    )
    values = np.zeros(384)
    values[:8] = 1
    suggestion = TopicAssigner(
        ManyTopicEncoder(), topics=topics, min_similarity=0
    ).suggest(uuid.uuid4(), [values.tolist()])
    assert len(suggestion.topic_similarities) == 8
    assert [item.topic_id for item in suggestion.topic_similarities] == list("abcdefgh")
    assert suggestion.top_topic_id == suggestion.topic_id == "a"
    assert suggestion.runner_up_topic_id == "b"
    assert suggestion.top_two_cosine_margin == pytest.approx(0)


def test_prototypes_are_cached_per_assigner() -> None:
    encoder = Encoder()
    assigner = TopicAssigner(encoder, topics=TOPICS)
    assigner.suggest(uuid.uuid4(), [vector(1)])
    assigner.suggest(uuid.uuid4(), [vector(0, 1)])
    assert len(encoder.calls) == 1


def test_schema_rejects_inconsistent_assignment() -> None:
    # Legacy construction remains valid because transparency fields are additive and optional.
    legacy = TopicSuggestion(
        page_id=uuid.uuid4(), status="suggested", topic_id="a",
        similarity=0.5, embedding_count=1,
    )
    assert legacy.evidence_status is None
    with pytest.raises(ValidationError):
        TopicSuggestion(page_id=uuid.uuid4(), status="suggested", topic_id=None,
                        similarity=None, embedding_count=1)
    with pytest.raises(ValidationError):
        TopicSuggestion(page_id=uuid.uuid4(), status="unclassified", topic_id="a",
                        similarity=0.5, reason="missing_embeddings", embedding_count=0)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


def test_scoped_query_filters_user_and_current_model() -> None:
    user_id = uuid.uuid4()
    page_id = uuid.uuid4()
    session = FakeSession([(page_id, vector(1), 384), (page_id, vector(0, 1), 384)])
    response = assign_user_pages(session, user_id, TopicAssigner(Encoder(), topics=TOPICS))
    assert response.taxonomy_version == TAXONOMY_VERSION
    assert response.page_count == response.suggested_count == 1
    assert response.assignments[0].embedding_count == 2
    compiled = session.statement.compile()
    sql = str(compiled)
    assert "pages.user_id =" in sql
    assert "page_chunk_embeddings.user_id =" in sql
    assert "page_chunk_embeddings.embedding_model =" in sql
    assert user_id in compiled.params.values()
    assert "test/model-v1" in compiled.params.values()


def test_endpoint_validation_and_empty_user_response_without_database() -> None:
    app = create_app(make_settings())
    fake = FakeSession([])
    app.dependency_overrides[get_db_session] = lambda: fake
    with TestClient(app) as client:
        assert client.get("/api/v1/topics/assignments?user_id=bad").status_code == 422
        response = client.get(f"/api/v1/topics/assignments?user_id={uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["page_count"] == 0
    assert response.json()["assignments"] == []
