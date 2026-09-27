"""Semantic retrieval service: query encoding, pgvector ordering, and tenant isolation."""

from collections.abc import Sequence

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.models.page_chunk_embedding import EMBEDDING_DIMENSION
from app.schemas.search import SearchRequest
from app.services.embeddings import EmbeddingRole
from app.services.search import TEXT_PREVIEW_MAX, EncoderUnavailableError, semantic_search
from tests.factories import (
    make_page,
    make_page_chunk,
    make_page_chunk_embedding,
    make_user,
)


MODEL_ID = "test/model-v1"


def unit_vector(*components: float) -> list[float]:
    array = np.zeros(EMBEDDING_DIMENSION, dtype=np.float64)
    for index, value in enumerate(components):
        array[index] = value
    norm = np.linalg.norm(array)
    assert norm > 0
    return (array / norm).tolist()


class RecordingEncoder:
    model_id = MODEL_ID
    dimension = EMBEDDING_DIMENSION

    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
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
        raise RuntimeError("weights missing at /models/BAAI/bge-small-en-v1.5")

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]:
        raise RuntimeError("weights missing")


@pytest.mark.db
def test_query_embedding_uses_role_query(db_session: Session) -> None:
    user = make_user(db_session)
    encoder = RecordingEncoder(unit_vector(1.0))
    request = SearchRequest(user_id=user.id, query="python tutorial I opened last week")

    semantic_search(db_session, encoder, request)

    assert encoder.calls == [("python tutorial I opened last week", "query")]


@pytest.mark.db
def test_results_are_ordered_by_cosine_distance_and_include_page_metadata(
    db_session: Session,
) -> None:
    user = make_user(db_session)
    query = unit_vector(1.0)
    exact = unit_vector(1.0)
    close = unit_vector(0.8, 0.2)
    orthogonal = unit_vector(0.0, 1.0)

    page_a = make_page(db_session, user, "https://docs.python.org/tutorial", title="Python tutorial")
    page_b = make_page(db_session, user, "https://example.com/unrelated", title="Unrelated")
    page_c = make_page(db_session, user, "https://docs.python.org/tutorial#later", title="Python later")

    chunk_exact = make_page_chunk(db_session, page_a, "How to install Python from python.org.", chunk_index=0)
    chunk_close = make_page_chunk(db_session, page_c, "A later section of the same tutorial.", chunk_index=0)
    chunk_far = make_page_chunk(db_session, page_b, "A completely different topic.", chunk_index=0)
    extra_on_same_page = make_page_chunk(
        db_session, page_a, "Second chunk of the python tutorial page.", chunk_index=1
    )

    make_page_chunk_embedding(db_session, user, page_a, chunk_exact, exact)
    make_page_chunk_embedding(db_session, user, page_c, chunk_close, close)
    make_page_chunk_embedding(db_session, user, page_b, chunk_far, orthogonal)
    make_page_chunk_embedding(db_session, user, page_a, extra_on_same_page, unit_vector(0.2, 0.8))

    encoder = RecordingEncoder(query)
    response = semantic_search(
        db_session, encoder, SearchRequest(user_id=user.id, query="python tutorial", limit=10)
    )

    assert [hit.chunk_id for hit in response.results][:3] == [
        chunk_exact.id,
        chunk_close.id,
        extra_on_same_page.id,
    ]
    assert response.results[0].cosine_distance == pytest.approx(0.0, abs=1e-6)
    assert response.results[0].similarity == pytest.approx(1.0, abs=1e-6)
    for hit in response.results:
        assert hit.similarity == pytest.approx(1.0 - hit.cosine_distance)
    top = response.results[0]
    assert top.page_id == page_a.id
    assert top.canonical_url == "https://docs.python.org/tutorial"
    assert top.title == "Python tutorial"
    assert top.domain == "docs.python.org"
    assert top.chunk_index == 0
    assert "install Python" in top.text_preview
    assert extra_on_same_page.id in {hit.chunk_id for hit in response.results}


@pytest.mark.db
def test_top_k_limit_is_applied(db_session: Session) -> None:
    user = make_user(db_session)
    page = make_page(db_session, user)
    encoder = RecordingEncoder(unit_vector(1.0))
    for index, x in enumerate((1.0, 0.7, 0.4, 0.1)):
        chunk = make_page_chunk(db_session, page, f"passage {index}", chunk_index=index)
        make_page_chunk_embedding(db_session, user, page, chunk, unit_vector(x, 1.0 - x))

    response = semantic_search(
        db_session, encoder, SearchRequest(user_id=user.id, query="anything", limit=2)
    )

    assert response.result_count == 2
    assert response.limit == 2
    assert response.results[0].cosine_distance <= response.results[1].cosine_distance


@pytest.mark.db
def test_zero_results_returns_an_empty_list(db_session: Session) -> None:
    user = make_user(db_session)
    encoder = RecordingEncoder(unit_vector(1.0))

    response = semantic_search(
        db_session, encoder, SearchRequest(user_id=user.id, query="nothing stored")
    )

    assert response.results == []
    assert response.result_count == 0
    assert response.query == "nothing stored"
    assert response.latency_ms >= 0


@pytest.mark.db
def test_search_never_returns_another_users_chunks(db_session: Session) -> None:
    owner = make_user(db_session)
    stranger = make_user(db_session)
    query = unit_vector(1.0)

    owner_page = make_page(db_session, owner, "https://example.com/mine", title="Mine")
    stranger_page = make_page(db_session, stranger, "https://example.com/secret", title="Secret")
    owner_chunk = make_page_chunk(db_session, owner_page, "owner passage about gardening")
    stranger_chunk = make_page_chunk(db_session, stranger_page, "secret perfect match about python")

    make_page_chunk_embedding(db_session, owner, owner_page, owner_chunk, unit_vector(0.0, 1.0))
    make_page_chunk_embedding(db_session, stranger, stranger_page, stranger_chunk, query)

    response = semantic_search(
        db_session,
        RecordingEncoder(query),
        SearchRequest(user_id=owner.id, query="python"),
    )

    assert [hit.chunk_id for hit in response.results] == [owner_chunk.id]
    assert all(hit.page_id == owner_page.id for hit in response.results)
    assert stranger_chunk.id not in {hit.chunk_id for hit in response.results}


@pytest.mark.db
def test_text_preview_is_truncated(db_session: Session) -> None:
    user = make_user(db_session)
    page = make_page(db_session, user)
    long_text = "word " * 200
    chunk = make_page_chunk(db_session, page, long_text)
    make_page_chunk_embedding(db_session, user, page, chunk, unit_vector(1.0))

    response = semantic_search(
        db_session, RecordingEncoder(unit_vector(1.0)), SearchRequest(user_id=user.id, query="word")
    )

    assert len(response.results[0].text_preview) == TEXT_PREVIEW_MAX
    assert response.results[0].text_preview.endswith("…")


@pytest.mark.db
def test_encoder_failure_is_encoder_unavailable(db_session: Session) -> None:
    user = make_user(db_session)
    with pytest.raises(EncoderUnavailableError, match="unavailable"):
        semantic_search(
            db_session, ExplodingEncoder(), SearchRequest(user_id=user.id, query="python")
        )
