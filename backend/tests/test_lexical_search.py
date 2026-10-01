"""B0 lexical retrieval: request contract and PostgreSQL FTS behavior."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.models import PageChunk, User
from app.schemas.lexical_search import LexicalSearchRequest
from tests.factories import make_page, make_page_chunk, make_settings, make_user

ENDPOINT = "/api/v1/search/lexical"
RESULT_FIELDS = {
    "chunk_id",
    "page_id",
    "canonical_url",
    "title",
    "domain",
    "chunk_index",
    "text_preview",
    "last_seen_at",
    "lexical_score",
}


@dataclass(frozen=True)
class Owner:
    user_id: uuid.UUID


def body(owner: Owner, query: str = "python installation", **overrides: object) -> dict[str, object]:
    return {"user_id": str(owner.user_id), "query": query, **overrides}


@pytest.fixture
def offline_client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def client(migrated_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(migrated_settings), raise_server_exceptions=False) as test_client:
        yield test_client


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


def test_query_is_stripped_and_empty_input_is_rejected() -> None:
    request = LexicalSearchRequest(user_id=uuid.uuid4(), query="  python installation  ")
    assert request.query == "python installation"

    with pytest.raises(ValueError, match="query must not be empty"):
        LexicalSearchRequest(user_id=uuid.uuid4(), query="   ")


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": str(uuid.uuid4()), "query": "   "},
        {"user_id": str(uuid.uuid4()), "query": "python", "limit": 0},
        {"user_id": "not-a-uuid", "query": "python"},
        {"user_id": str(uuid.uuid4()), "query": "x" * 1001},
    ],
)
def test_invalid_lexical_query_gets_422(offline_client: TestClient, payload: dict[str, object]) -> None:
    response = offline_client.post(ENDPOINT, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_lexical_openapi_uses_distinct_score_field(offline_client: TestClient) -> None:
    schema = offline_client.get("/openapi.json").json()
    endpoint = schema["paths"][ENDPOINT]["post"]
    assert "websearch_to_tsquery" in endpoint["description"]
    fields = schema["components"]["schemas"]["LexicalSearchResult"]["properties"]
    assert set(fields) == RESULT_FIELDS
    assert "ts_rank_cd" in fields["lexical_score"]["description"]
    assert "cosine_distance" not in fields and "similarity" not in fields


@pytest.mark.db
def test_postgres_fts_ranks_closer_terms_first_and_scopes_results_to_user(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner, stranger = make_owner(), make_owner()
    factory = sessionmaker(bind=engine)
    with factory() as session:
        own_page = make_page(session, session.get(User, owner.user_id), "https://example.com/own")
        foreign_page = make_page(
            session, session.get(User, stranger.user_id), "https://example.com/secret"
        )
        close = make_page_chunk(session, own_page, "Python installation guide for Linux systems.")
        distant = make_page_chunk(
            session,
            own_page,
            "Installation notes cover unrelated subjects before a Python appendix.",
            chunk_index=1,
        )
        secret = make_page_chunk(
            session, foreign_page, "Python installation guide with a perfect exact match."
        )
        close_id, distant_id, secret_id = close.id, distant.id, secret.id
        session.commit()

    response = client.post(ENDPOINT, json=body(owner, "python installation"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "python installation"
    assert payload["result_count"] == 2
    assert [hit["chunk_id"] for hit in payload["results"]] == [str(close_id), str(distant_id)]
    assert payload["results"][0]["lexical_score"] > payload["results"][1]["lexical_score"]
    assert set(payload["results"][0]) == RESULT_FIELDS
    assert all(hit["page_id"] != str(secret_id) for hit in payload["results"])
    assert payload["latency_ms"] >= 0


@pytest.mark.db
def test_lexical_search_returns_empty_results_for_no_match(
    client: TestClient, make_owner: Callable[[], Owner]
) -> None:
    response = client.post(ENDPOINT, json=body(make_owner(), "unmatched search phrase"))

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["result_count"] == 0
