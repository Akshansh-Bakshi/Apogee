"""Encoder unit coverage and explicitly isolated embedding-persistence integration tests."""

from collections.abc import Sequence
import uuid

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PageChunkEmbedding
from app.services.embeddings import (
    EmbeddingRole,
    SentenceTransformerEncoder,
    create_embedding_encoder,
    embed_page_chunk,
)
from tests.factories import count, make_page, make_page_chunk, make_settings, make_user


class FakeSentenceTransformer:
    def __init__(self, vectors: np.ndarray | None = None) -> None:
        self.inputs: list[str] = []
        self.vectors = vectors
        self.eval_called = False

    def eval(self) -> None:
        self.eval_called = True

    def encode(self, texts: Sequence[str], **_: object) -> np.ndarray:
        self.inputs.extend(texts)
        if self.vectors is not None:
            return self.vectors
        return np.tile(np.arange(1, 385, dtype=np.float32), (len(texts), 1))


class FakeEncoder:
    model_id = "test/model-v1"
    dimension = 384

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [3.0, 4.0] + [0.0] * 382
        self.calls: list[list[str]] = []

    def encode_text(self, text: str, *, role: EmbeddingRole = "passage") -> list[float]:
        return self.encode_batch([text], role=role)[0]

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vector[:] for _ in texts]


def test_encoder_loads_configured_model_lazily_and_honours_offline_setting() -> None:
    settings = make_settings(
        embedding_model_id="BAAI/test-model",
        embedding_device="cpu",
        embedding_local_files_only=True,
    )
    calls: list[tuple[str, dict[str, object]]] = []
    model = FakeSentenceTransformer()

    def loader(model_id: str, **kwargs: object) -> FakeSentenceTransformer:
        calls.append((model_id, kwargs))
        return model

    encoder = create_embedding_encoder(settings)
    encoder._model_loader = loader
    assert calls == []
    assert encoder.encode_text("hello")
    assert calls == [
        (
            "BAAI/test-model",
            {"device": "cpu", "local_files_only": True},
        )
    ]
    assert model.eval_called


def test_single_and_batch_encoding_are_384_dimensional_unit_normalized_and_repeatable() -> None:
    model = FakeSentenceTransformer()
    encoder = SentenceTransformerEncoder("BAAI/bge-small-en-v1.5", model_loader=lambda *_a, **_k: model)

    single = encoder.encode_text("Apogee stores pages locally.")
    batch_first = encoder.encode_batch(["one", "two"])
    batch_second = encoder.encode_batch(["one", "two"])

    assert len(single) == 384
    assert np.linalg.norm(single) == pytest.approx(1.0)
    assert batch_first == batch_second
    assert all(len(vector) == 384 for vector in batch_first)
    assert all(np.linalg.norm(vector) == pytest.approx(1.0) for vector in batch_first)


def test_bge_adds_documented_instruction_only_to_query_text() -> None:
    model = FakeSentenceTransformer()
    encoder = create_embedding_encoder(make_settings())
    encoder._model_loader = lambda *_a, **_k: model

    encoder.encode_batch(["find this"], role="query")
    encoder.encode_batch(["stored passage"], role="passage")

    assert model.inputs == [
        "Represent this sentence for searching relevant passages: find this",
        "stored passage",
    ]


@pytest.mark.parametrize("text", ["", "  ", None, 123])
def test_encoder_rejects_empty_or_invalid_text(text: object) -> None:
    encoder = SentenceTransformerEncoder("BAAI/bge-small-en-v1.5", model_loader=lambda *_a, **_k: FakeSentenceTransformer())
    with pytest.raises(ValueError):
        encoder.encode_text(text)  # type: ignore[arg-type]


def test_encoder_rejects_wrong_dimension_and_non_finite_vectors() -> None:
    short = FakeSentenceTransformer(np.zeros((1, 383), dtype=np.float32))
    encoder = SentenceTransformerEncoder("test/model", model_loader=lambda *_a, **_k: short)
    with pytest.raises(ValueError, match=r"expected \(1, 384\)"):
        encoder.encode_text("valid")

    non_finite = FakeSentenceTransformer(np.full((1, 384), np.nan))
    encoder = SentenceTransformerEncoder("test/model", model_loader=lambda *_a, **_k: non_finite)
    with pytest.raises(ValueError, match="non-finite"):
        encoder.encode_text("valid")


def test_empty_batch_is_a_noop_without_loading_model() -> None:
    encoder = SentenceTransformerEncoder("test/model", model_loader=lambda *_a, **_k: pytest.fail("loaded"))
    assert encoder.encode_batch([]) == []


def test_batch_encoder_rejects_non_sequence_input() -> None:
    encoder = SentenceTransformerEncoder("test/model")
    with pytest.raises(ValueError, match="sequence"):
        encoder.encode_batch(None)  # type: ignore[arg-type]


def test_batch_encoder_rejects_unknown_role() -> None:
    encoder = SentenceTransformerEncoder("test/model")
    with pytest.raises(ValueError, match="role"):
        encoder.encode_batch([], role="other")  # type: ignore[arg-type]


def test_configured_model_identity_is_used() -> None:
    encoder = create_embedding_encoder(make_settings(embedding_model_id="local/bge-small-v1"))
    assert encoder.model_id == "local/bge-small-v1"
    assert encoder.dimension == 384


@pytest.mark.db
def test_chunk_embedding_upsert_replaces_same_model_and_keeps_other_model(db_session: Session) -> None:
    user = make_user(db_session)
    page = make_page(db_session, user)
    chunk = make_page_chunk(db_session, page)
    first_encoder = FakeEncoder()

    first = embed_page_chunk(db_session, chunk.id, first_encoder)
    first_id = first.id
    assert first.embedding_model == "test/model-v1"
    assert first.embedding_dimension == 384
    assert first.embedding[:2] == pytest.approx([0.6, 0.8])
    assert count(db_session, PageChunkEmbedding, page_chunk_id=chunk.id) == 1

    first_encoder.vector = [0.0, 5.0] + [0.0] * 382
    repeated = embed_page_chunk(db_session, chunk.id, first_encoder)
    assert repeated.id == first_id
    assert repeated.embedding[:2] == pytest.approx([0.0, 1.0])
    assert count(db_session, PageChunkEmbedding, page_chunk_id=chunk.id) == 1

    second = FakeEncoder()
    second.model_id = "test/model-v2"
    embed_page_chunk(db_session, chunk.id, second)
    assert count(db_session, PageChunkEmbedding, page_chunk_id=chunk.id) == 2


@pytest.mark.db
def test_chunk_embedding_persistence_rolls_back_with_caller_transaction(db_session: Session) -> None:
    user = make_user(db_session)
    page = make_page(db_session, user)
    chunk = make_page_chunk(db_session, page)

    with pytest.raises(RuntimeError, match="abort caller transaction"):
        with db_session.begin_nested():
            embed_page_chunk(db_session, chunk.id, FakeEncoder())
            raise RuntimeError("abort caller transaction")

    assert db_session.scalar(
        select(PageChunkEmbedding.id).where(PageChunkEmbedding.page_chunk_id == chunk.id)
    ) is None


@pytest.mark.db
def test_unknown_chunk_is_rejected_without_writing(db_session: Session) -> None:
    with pytest.raises(ValueError, match="do not exist"):
        embed_page_chunk(db_session, uuid.uuid4(), FakeEncoder())
    assert count(db_session, PageChunkEmbedding) == 0
