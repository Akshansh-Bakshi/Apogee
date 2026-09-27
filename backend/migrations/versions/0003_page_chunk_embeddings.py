"""Add model-versioned, normalized 384-dimensional chunk embeddings.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_page_chunks_id_page_id", "page_chunks", ["id", "page_id"]
    )
    op.create_table(
        "page_chunk_embeddings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("page_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model", sa.String(length=512), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), server_default="384", nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "embedding_dimension = 384", name="ck_page_chunk_embeddings_dimension_384"
        ),
        sa.ForeignKeyConstraint(
            ["page_chunk_id", "page_id"],
            ["page_chunks.id", "page_chunks.page_id"],
            name="fk_page_chunk_embeddings_chunk_page",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "user_id"],
            ["pages.id", "pages.user_id"],
            name="fk_page_chunk_embeddings_page_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_page_chunk_embeddings"),
        sa.UniqueConstraint(
            "page_chunk_id", "embedding_model", name="uq_page_chunk_embeddings_chunk_model"
        ),
    )
    op.create_index(
        "ix_page_chunk_embeddings_user_id", "page_chunk_embeddings", ["user_id"]
    )
    op.create_index(
        "ix_page_chunk_embeddings_embedding_hnsw",
        "page_chunk_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("page_chunk_embeddings")
    op.drop_constraint("uq_page_chunks_id_page_id", "page_chunks", type_="unique")
