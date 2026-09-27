"""Local, model-abstracted text encoding and PageChunk embedding persistence.

The service does not commit: the caller owns the SQLAlchemy transaction and can combine embedding
writes with other work or roll them back. It stores page ownership alongside each vector so later
retrieval has an explicit tenant scope.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol
import uuid

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Page, PageChunk, PageChunkEmbedding
from app.models.page_chunk_embedding import EMBEDDING_DIMENSION

EmbeddingRole = Literal["query", "passage"]


class EmbeddingEncoder(Protocol):
    """The narrow encoding interface used by persistence and, later, retrieval."""

    model_id: str
    dimension: int

    def encode_text(self, text: str, *, role: EmbeddingRole = "passage") -> list[float]: ...

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]: ...


def _validated_texts(texts: Sequence[str]) -> list[str]:
    if not isinstance(texts, Sequence) or isinstance(texts, (str, bytes)):
        raise ValueError("texts must be a sequence of non-empty strings")
    result = list(texts)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError("text must be a non-empty string")
    return result


def normalize_vectors(vectors: object, *, expected_rows: int) -> list[list[float]]:
    """Validate model output and return finite, exactly 384-dimensional unit vectors."""
    array = np.asarray(vectors, dtype=np.float64)
    if expected_rows == 1 and array.shape == (EMBEDDING_DIMENSION,):
        array = array.reshape(1, -1)
    if array.shape != (expected_rows, EMBEDDING_DIMENSION):
        raise ValueError(
            f"encoder returned shape {array.shape}; expected ({expected_rows}, {EMBEDDING_DIMENSION})"
        )
    if not np.isfinite(array).all():
        raise ValueError("encoder output contains a non-finite value")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("encoder output contains a zero vector")
    return (array / norms).tolist()


class SentenceTransformerEncoder:
    """Lazy CPU-first Sentence Transformers adapter with BGE query/passage conventions."""

    dimension = EMBEDDING_DIMENSION

    def __init__(
        self,
        model_id: str,
        *,
        device: str = "cpu",
        local_files_only: bool = False,
        query_instruction: str = "",
        model_loader: object | None = None,
    ) -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        self.model_id = model_id
        self.device = device
        self.local_files_only = local_files_only
        self.query_instruction = query_instruction
        self._model_loader = model_loader
        self._model: object | None = None

    def load(self) -> SentenceTransformerEncoder:
        """Load weights explicitly; with local_files_only=True no network access is attempted."""
        if self._model is None:
            loader = self._model_loader
            if loader is None:
                from sentence_transformers import SentenceTransformer

                loader = SentenceTransformer
            self._model = loader(
                self.model_id,
                device=self.device,
                local_files_only=self.local_files_only,
            )
            if hasattr(self._model, "eval"):
                self._model.eval()
        return self

    def encode_text(self, text: str, *, role: EmbeddingRole = "passage") -> list[float]:
        vectors = self.encode_batch([text], role=role)
        return vectors[0]

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]:
        if role not in ("query", "passage"):
            raise ValueError("role must be 'query' or 'passage'")
        clean_texts = _validated_texts(texts)
        if not clean_texts:
            return []
        query_prefix = self.query_instruction
        if query_prefix and not query_prefix[-1].isspace():
            query_prefix += " "
        inputs = [query_prefix + item for item in clean_texts] if role == "query" else clean_texts
        model = self._model if self._model is not None else self.load()._model
        raw = model.encode(  # type: ignore[union-attr]
            inputs,
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        return normalize_vectors(raw, expected_rows=len(clean_texts))


def create_embedding_encoder(settings: Settings) -> SentenceTransformerEncoder:
    """Build the configured local encoder without loading weights until first use."""
    return SentenceTransformerEncoder(
        settings.embedding_model_id,
        device=settings.embedding_device,
        local_files_only=settings.embedding_local_files_only,
        query_instruction=settings.embedding_query_instruction,
    )


def embed_page_chunk(
    session: Session, page_chunk_id: uuid.UUID, encoder: EmbeddingEncoder
) -> PageChunkEmbedding:
    """Encode and upsert one chunk's passage vector; the caller controls commit/rollback."""
    return embed_page_chunks(session, [page_chunk_id], encoder)[0]


def embed_page_chunks(
    session: Session, page_chunk_ids: Sequence[uuid.UUID], encoder: EmbeddingEncoder
) -> list[PageChunkEmbedding]:
    """Batch encode and upsert chunks, unique per ``(page_chunk_id, model_id)``.

    Re-embedding with the same model replaces the existing vector and updates ``updated_at``;
    a different model id creates a separate row. An empty ID list is a no-op. This function
    flushes writes so constraint failures happen here but deliberately does not commit.
    """
    if not page_chunk_ids:
        return []
    if any(not isinstance(chunk_id, uuid.UUID) for chunk_id in page_chunk_ids):
        raise ValueError("page_chunk_ids must contain UUIDs")
    ids = list(dict.fromkeys(page_chunk_ids))
    rows = session.execute(
        select(PageChunk, Page.user_id)
        .join(Page, Page.id == PageChunk.page_id)
        .where(PageChunk.id.in_(ids))
    ).all()
    chunks = {chunk.id: (chunk, user_id) for chunk, user_id in rows}
    missing = [chunk_id for chunk_id in ids if chunk_id not in chunks]
    if missing:
        raise ValueError("one or more page chunks do not exist")

    ordered = [chunks[chunk_id] for chunk_id in ids]
    vectors = normalize_vectors(
        encoder.encode_batch([chunk.text for chunk, _ in ordered], role="passage"),
        expected_rows=len(ordered),
    )
    insert = pg_insert(PageChunkEmbedding).values(
        [
            {
                "page_chunk_id": chunk.id,
                "page_id": chunk.page_id,
                "user_id": user_id,
                "embedding_model": encoder.model_id,
                "embedding_dimension": EMBEDDING_DIMENSION,
                "embedding": vector,
            }
            for (chunk, user_id), vector in zip(ordered, vectors, strict=True)
        ]
    )
    statement = insert.on_conflict_do_update(
        index_elements=["page_chunk_id", "embedding_model"],
        set_={
            "page_id": insert.excluded.page_id,
            "user_id": insert.excluded.user_id,
            "embedding_dimension": insert.excluded.embedding_dimension,
            "embedding": insert.excluded.embedding,
            "updated_at": func.now(),
        },
    ).returning(PageChunkEmbedding.id)
    embedding_ids = session.scalars(statement).all()
    session.flush()
    return list(
        session.scalars(
            select(PageChunkEmbedding)
            .where(PageChunkEmbedding.id.in_(embedding_ids))
            .execution_options(populate_existing=True)
        ).all()
    )
