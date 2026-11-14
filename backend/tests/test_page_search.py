"""Page retrieval preserves best-chunk evidence without chunk crowding."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_db_session
from app.main import create_app
from app.schemas.page_search import PageSearchRequest
from app.schemas.search import SearchRequest
from app.schemas.lexical_search import LexicalSearchRequest
from app.services.page_search import page_search
from app.services.search import semantic_search
from app.services.lexical_search import lexical_search
from tests.factories import make_user, make_page, make_page_chunk, make_page_chunk_embedding, make_settings
from tests.test_search import RecordingEncoder, unit_vector


@pytest.mark.parametrize("payload", [
    {"limit": 0}, {"limit": 51}, {"offset": -1}, {"offset": 50},
    {"offset": 45, "limit": 10}, {"mode": "hybrid"}, {"query": " "},
])
def test_page_request_validates_bounds_and_mode(payload):
    values = dict(user_id=uuid4(), query="game development")
    values.update(payload)
    with pytest.raises(ValidationError):
        PageSearchRequest(**values)


def test_page_api_and_chunk_contracts_remain_available():
    with TestClient(create_app(make_settings())) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert {"/api/v1/search", "/api/v1/search/lexical", "/api/v1/search/pages"} <= set(paths)
        assert client.post("/api/v1/search/pages", json={"user_id": "invalid"}).status_code == 422


@pytest.mark.db
@pytest.mark.parametrize("mode", ["semantic", "lexical"])
def test_best_scoring_chunk_selected_before_page_limit(db_session, mode):
    user = make_user(db_session)
    a = make_page(db_session, user, "https://example.com/a")
    b = make_page(db_session, user, "https://example.com/b")
    for page, index, content, vector in [
        (a, 0, "Game notes and unrelated details about development.", unit_vector(0.1, 1)),
        (a, 1, "Game development. Game development.", unit_vector(1)),
        (a, 2, "Game development.", unit_vector(0.9, 0.1)),
        (b, 0, "Game guide to development.", unit_vector(0.7, 0.3)),
    ]:
        chunk = make_page_chunk(db_session, page, content, chunk_index=index)
        make_page_chunk_embedding(db_session, user, page, chunk, vector)
    encoder = RecordingEncoder(unit_vector(1))
    request = PageSearchRequest(user_id=user.id, query="game development", mode=mode, limit=2)
    result = page_search(db_session, encoder, request)
    assert [hit.page_id for hit in result.results] == [a.id, b.id]
    assert result.results[0].chunk_index == 1
    limited = page_search(db_session, encoder, request.model_copy(update={"limit": 1}))
    assert limited.results == result.results[:1]
    assert limited.truncated


@pytest.mark.db
@pytest.mark.parametrize("mode", ["semantic", "lexical"])
def test_page_offset_preserves_global_order_without_repeating_pages(db_session, mode):
    user = make_user(db_session)
    for index in range(12):
        page = make_page(db_session, user, f"https://example.com/{index:02d}")
        chunk = make_page_chunk(db_session, page, "Game development guide.", chunk_index=0)
        make_page_chunk_embedding(db_session, user, page, chunk, unit_vector(1.0))
    encoder = RecordingEncoder(unit_vector(1.0))
    base = PageSearchRequest(user_id=user.id, query="game development", mode=mode, limit=10)
    first = page_search(db_session, encoder, base)
    second = page_search(db_session, encoder, base.model_copy(update={"offset": 10}))
    combined = page_search(db_session, encoder, base.model_copy(update={"limit": 12}))
    assert first.offset == 0 and first.result_count == 10 and first.truncated
    assert second.offset == 10 and second.result_count == 2 and not second.truncated
    assert not ({hit.page_id for hit in first.results} & {hit.page_id for hit in second.results})
    assert first.results + second.results == combined.results


@pytest.mark.db
@pytest.mark.parametrize("mode", ["semantic", "lexical"])
def test_page_diversity_best_chunk_limits_ties_and_isolation(db_session, mode):
    owner, stranger = make_user(db_session), make_user(db_session)
    pages = [make_page(db_session, owner, f"https://example.com/{i}") for i in range(3)]
    foreign = make_page(db_session, stranger, "https://example.com/private")
    for page, count in [(pages[0], 5), (pages[1], 2), (pages[2], 1), (foreign, 1)]:
        for i in range(count):
            chunk = make_page_chunk(db_session, page, "Game development guide.", chunk_index=i)
            make_page_chunk_embedding(db_session, owner if page != foreign else stranger,
                                      page, chunk, unit_vector(1.0))
    encoder = RecordingEncoder(unit_vector(1.0))
    request = PageSearchRequest(user_id=owner.id, query="game development", mode=mode, limit=2)
    result = page_search(db_session, encoder, request)
    assert len(result.results) == 2
    assert len({hit.page_id for hit in result.results}) == 2
    assert result.truncated
    assert result.result_state == "possible_matches"
    assert all(hit.page_id != foreign.id and hit.chunk_index == 0 for hit in result.results)
    again = page_search(db_session, encoder, request)
    assert [hit.chunk_id for hit in result.results] == [hit.chunk_id for hit in again.results]
    all_pages = page_search(db_session, encoder, request.model_copy(update={"limit": 50}))
    assert len(all_pages.results) == 3
    assert not all_pages.truncated
    if mode == "semantic":
        assert [hit.page_id for hit in all_pages.results] == sorted(page.id for page in pages)
        assert all(hit.similarity == pytest.approx(1.0) for hit in all_pages.results)
        assert len(encoder.calls) == 3  # one query encoding per request, never per page
        chunks = semantic_search(db_session, encoder, SearchRequest(user_id=owner.id, query="game", limit=50))
    else:
        chunks = lexical_search(db_session, LexicalSearchRequest(user_id=owner.id, query="game development", limit=50))
        expected = list(dict.fromkeys(hit.page_id for hit in chunks.results))
        assert [hit.page_id for hit in all_pages.results] == expected
        assert not encoder.calls
    assert chunks.result_count == 8  # original chunk API still retains duplicate-page hits


@pytest.mark.db
@pytest.mark.parametrize("mode, state", [("semantic", "insufficient_evidence"), ("lexical", "no_sufficient_match")])
def test_page_empty_user_and_api_response(db_session, mode, state):
    user = make_user(db_session)
    app = create_app(make_settings())
    app.dependency_overrides[get_db_session] = lambda: db_session
    with TestClient(app) as client:
        app.state.embedding_encoder = RecordingEncoder(unit_vector(1.0))
        response = client.post("/api/v1/search/pages", json={"user_id": str(user.id), "query": "unrelated", "mode": mode})
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["result_state"] == state
    assert response.json()["result_unit"] == "page"
    assert response.json()["truncated"] is False
