"""POST /api/v1/search through the real FastAPI application."""

import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.models import User
from app.models.page_chunk_embedding import EMBEDDING_DIMENSION
from app.services.embeddings import EmbeddingRole
from tests.factories import (
    make_page,
    make_page_chunk,
    make_page_chunk_embedding,
    make_settings,
    make_user,
)

ENDPOINT = "/api/v1/search"
MODEL_ID = "test/model-v1"
RESULT_FIELDS = {
    "chunk_id",
    "page_id",
    "canonical_url",
    "title",
    "domain",
    "chunk_index",
    "text_preview",
    "last_seen_at",
    "cosine_distance",
    "similarity",
}


def unit_vector(*components: float) -> list[float]:
    array = np.zeros(EMBEDDING_DIMENSION, dtype=np.float64)
    for index, value in enumerate(components):
        array[index] = value
    return (array / np.linalg.norm(array)).tolist()


class RecordingEncoder:
    model_id = MODEL_ID
    dimension = EMBEDDING_DIMENSION

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or unit_vector(1.0)
        self.calls: list[tuple[str, EmbeddingRole]] = []

    def encode_text(self, text: str, *, role: EmbeddingRole = "passage") -> list[float]:
        self.calls.append((text, role))
        return self.vector

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]:
        return [self.encode_text(text, role=role) for text in texts]


class ExplodingEncoder:
    model_id = MODEL_ID
    dimension = EMBEDDING_DIMENSION

    def encode_text(self, text: str, *, role: EmbeddingRole = "passage") -> list[float]:
        raise RuntimeError("SELECT embedding FROM page_chunk_embeddings")

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]:
        raise RuntimeError("SELECT embedding FROM page_chunk_embeddings")


@dataclass(frozen=True)
class Owner:
    user_id: uuid.UUID


def body(owner: Owner, query: str = "python tutorial", **overrides: object) -> dict[str, object]:
    return {"user_id": str(owner.user_id), "query": query, **overrides}


@pytest.fixture
def offline_client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def client(migrated_settings: Settings) -> Iterator[tuple[TestClient, RecordingEncoder]]:
    app = create_app(migrated_settings)
    encoder = RecordingEncoder()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        app.state.embedding_encoder = encoder
        yield test_client, encoder


@pytest.fixture
def make_owner(engine: Engine) -> Iterator[Callable[[], Owner]]:
    factory = sessionmaker(bind=engine)
    created: list[uuid.UUID] = []

    def create() -> Owner:
        with factory() as session:
            user = make_user(session)
            session.commit()
            created.append(user.id)
            return Owner(user.id)

    yield create

    with factory() as session:
        session.execute(delete(User).where(User.id.in_(created)))
        session.commit()


def test_empty_query_is_a_422(offline_client: TestClient) -> None:
    response = offline_client.post(
        ENDPOINT, json={"user_id": str(uuid.uuid4()), "query": "   "}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["body", "query"]


def test_invalid_limit_is_a_422(offline_client: TestClient) -> None:
    response = offline_client.post(
        ENDPOINT, json={"user_id": str(uuid.uuid4()), "query": "python", "limit": 0}
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", "limit"]


def test_invalid_user_id_is_a_422(offline_client: TestClient) -> None:
    response = offline_client.post(ENDPOINT, json={"user_id": "nope", "query": "python"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", "user_id"]


def test_openapi_documents_search_request_and_response(offline_client: TestClient) -> None:
    schema = offline_client.get("/openapi.json").json()
    path = schema["paths"][ENDPOINT]["post"]
    assert path["summary"]
    assert "top-K" in path["description"] or "top-K" in path["summary"]
    components = schema["components"]["schemas"]
    assert "SearchRequest" in components
    assert "SearchResponse" in components
    assert "SearchResult" in components
    assert set(components["SearchResult"]["properties"]) == RESULT_FIELDS
    assert "cosine_distance" in components["SearchResult"]["properties"]
    assert "1 - cosine_distance" in components["SearchResult"]["properties"]["similarity"]["description"]


def test_missing_encoder_is_a_503(offline_client: TestClient) -> None:
    offline_client.app.state.embedding_encoder = None
    response = offline_client.post(
        ENDPOINT, json={"user_id": str(uuid.uuid4()), "query": "python"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "encoder_unavailable"
    assert "Traceback" not in response.text


def test_encoder_failure_is_a_503_that_reveals_nothing(offline_client: TestClient) -> None:
    offline_client.app.state.embedding_encoder = ExplodingEncoder()
    response = offline_client.post(
        ENDPOINT, json={"user_id": str(uuid.uuid4()), "query": "python"}
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "encoder_unavailable"
    assert "SELECT" not in response.text
    assert "page_chunk_embeddings" not in response.text


def test_a_database_outage_is_a_503_that_reveals_nothing(offline_client: TestClient) -> None:
    offline_client.app.state.embedding_encoder = RecordingEncoder()
    response = offline_client.post(
        ENDPOINT, json={"user_id": str(uuid.uuid4()), "query": "python"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    for leaked in ("unit-test-secret", "127.0.0.1", "postgres", "SELECT", "Traceback"):
        assert leaked not in response.text


def test_search_reuses_the_encoder_on_app_state(offline_client: TestClient) -> None:
    encoder = RecordingEncoder()
    offline_client.app.state.embedding_encoder = encoder
    payload = {"user_id": str(uuid.uuid4()), "query": "python"}

    first = offline_client.post(ENDPOINT, json=payload)
    second = offline_client.post(ENDPOINT, json=payload)

    # Unreachable DB, but both requests used the same encoder instance before the query ran...
    # Encoding happens before the SQL, so role=query is recorded even when the DB is down.
    assert encoder is offline_client.app.state.embedding_encoder
    assert encoder.calls == [("python", "query"), ("python", "query")]
    assert first.status_code == 503
    assert second.status_code == 503


@pytest.mark.db
def test_successful_semantic_search_returns_ranked_chunks_with_page_metadata(
    client: tuple[TestClient, RecordingEncoder], engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    test_client, encoder = client
    owner = make_owner()
    other = make_owner()
    factory = sessionmaker(bind=engine)

    with factory() as session:
        user = session.get(User, owner.user_id)
        stranger = session.get(User, other.user_id)
        assert user is not None and stranger is not None
        page = make_page(session, user, "https://docs.python.org/3/tutorial/", title="Tutorial")
        other_page = make_page(session, stranger, "https://evil.example/secret", title="Secret")
        close = make_page_chunk(session, page, "Installing Python from python.org.", chunk_index=0)
        far = make_page_chunk(session, page, "Unrelated appendix material.", chunk_index=1)
        secret = make_page_chunk(session, other_page, "Perfect semantic match that must stay hidden.")
        make_page_chunk_embedding(session, user, page, close, unit_vector(1.0))
        make_page_chunk_embedding(session, user, page, far, unit_vector(0.0, 1.0))
        make_page_chunk_embedding(session, stranger, other_page, secret, unit_vector(1.0))
        session.commit()
        close_id, far_id, page_id, secret_id = close.id, far.id, page.id, secret.id

    encoder.vector = unit_vector(1.0)
    response = test_client.post(
        ENDPOINT, json=body(owner, query="  how did I install python  ", limit=10)
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "how did I install python"
    assert payload["limit"] == 10
    assert payload["result_count"] == 2
    assert payload["latency_ms"] >= 0
    assert set(payload["results"][0]) == RESULT_FIELDS
    assert [hit["chunk_id"] for hit in payload["results"]] == [str(close_id), str(far_id)]
    top = payload["results"][0]
    assert top["page_id"] == str(page_id)
    assert top["canonical_url"] == "https://docs.python.org/3/tutorial/"
    assert top["title"] == "Tutorial"
    assert top["domain"] == "docs.python.org"
    assert top["chunk_index"] == 0
    assert "Installing Python" in top["text_preview"]
    assert top["cosine_distance"] == pytest.approx(0.0, abs=1e-5)
    assert top["similarity"] == pytest.approx(1.0 - top["cosine_distance"])
    assert all(hit["chunk_id"] != str(secret_id) for hit in payload["results"])
    assert all(hit["page_id"] == str(page_id) for hit in payload["results"])
    assert encoder.calls[-1] == ("how did I install python", "query")


@pytest.mark.db
def test_zero_result_query_is_200_with_empty_results(
    client: tuple[TestClient, RecordingEncoder], make_owner: Callable[[], Owner]
) -> None:
    test_client, _encoder = client
    owner = make_owner()
    response = test_client.post(ENDPOINT, json=body(owner, query="no embeddings yet"))
    assert response.status_code == 200
    body_json = response.json()
    assert body_json["results"] == []
    assert body_json["result_count"] == 0
