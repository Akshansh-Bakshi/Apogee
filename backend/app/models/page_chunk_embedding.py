"""Model-versioned dense embeddings for page chunks."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EMBEDDING_DIMENSION = 384


class PageChunkEmbedding(Base):
    """One embedding for a chunk under a particular model identifier.

    ``user_id`` is stored for every scoped embedding operation and protected by composite
    foreign keys tying it to both the chunk's page and its owning user. It also gives future
    retrieval a direct tenant filter alongside the HNSW vector index.
    """

    __tablename__ = "page_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "page_chunk_id", "embedding_model", name="uq_page_chunk_embeddings_chunk_model"
        ),
        CheckConstraint(
            f"embedding_dimension = {EMBEDDING_DIMENSION}",
            name="ck_page_chunk_embeddings_dimension_384",
        ),
        ForeignKeyConstraint(
            ["page_chunk_id", "page_id"],
            ["page_chunks.id", "page_chunks.page_id"],
            name="fk_page_chunk_embeddings_chunk_page",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["page_id", "user_id"],
            ["pages.id", "pages.user_id"],
            name="fk_page_chunk_embeddings_page_user",
            ondelete="CASCADE",
        ),
        Index("ix_page_chunk_embeddings_user_id", "user_id"),
        Index(
            "ix_page_chunk_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    page_chunk_id: Mapped[uuid.UUID] = mapped_column()
    page_id: Mapped[uuid.UUID] = mapped_column()
    user_id: Mapped[uuid.UUID] = mapped_column()
    embedding_model: Mapped[str] = mapped_column(String(512))
    embedding_dimension: Mapped[int] = mapped_column(
        Integer, default=EMBEDDING_DIMENSION, server_default=text(str(EMBEDDING_DIMENSION))
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
