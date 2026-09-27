"""Request validation for POST /api/v1/search. No database needed."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.search import MAX_LIMIT, MAX_QUERY_LENGTH, SearchRequest

USER_ID = "6f1f7d2e-3b8a-4c55-9a1e-0d3f5a7b9c11"


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "user_id": USER_ID,
        "query": "the python tutorial I read yesterday",
        "limit": 10,
    }
    return {**base, **overrides}


def test_a_valid_request_is_parsed_and_query_whitespace_is_stripped() -> None:
    request = SearchRequest(**payload(query="  the python tutorial  ", limit=5))

    assert request.user_id == uuid.UUID(USER_ID)
    assert request.query == "the python tutorial"
    assert request.limit == 5


def test_limit_defaults_to_ten() -> None:
    request = SearchRequest(user_id=uuid.UUID(USER_ID), query="python tutorial")
    assert request.limit == 10


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_empty_or_whitespace_query_is_rejected(query: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        SearchRequest(**payload(query=query))
    assert any(error["loc"] == ("query",) for error in excinfo.value.errors())


def test_query_longer_than_the_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(**payload(query="x" * (MAX_QUERY_LENGTH + 1)))


@pytest.mark.parametrize("limit", [0, -1, MAX_LIMIT + 1])
def test_limit_outside_one_to_max_is_rejected(limit: int) -> None:
    with pytest.raises(ValidationError) as excinfo:
        SearchRequest(**payload(limit=limit))
    assert any(error["loc"] == ("limit",) for error in excinfo.value.errors())


def test_invalid_user_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(**payload(user_id="not-a-uuid"))


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(**payload(cookies="sid=hunter2"))
