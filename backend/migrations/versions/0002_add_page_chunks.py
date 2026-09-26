"""Add page_chunks: deterministic slices of a page's cleaned text.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24

No vector column is added here (see 0001): the embedding model, and therefore the vector
dimensionality, has still not been chosen. This migration only gives chunked text somewhere
normalized to live, ahead of that decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_DEFAULT = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "page_chunks",
        sa.Column("id", sa.Uuid(), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_page_chunks"),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"], name="fk_page_chunks_page_id_pages", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("page_id", "chunk_index", name="uq_page_chunks_page_id_chunk_index"),
        sa.CheckConstraint("char_end > char_start", name="ck_page_chunks_char_end_after_char_start"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_page_chunks_chunk_index_non_negative"),
    )
    op.create_index("ix_page_chunks_page_id", "page_chunks", ["page_id"])


def downgrade() -> None:
    op.drop_table("page_chunks")
