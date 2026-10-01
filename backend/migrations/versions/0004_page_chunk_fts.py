"""Add a GIN expression index for English full-text search over chunk text.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_page_chunks_text_fts",
        "page_chunks",
        [sa.text("to_tsvector('english'::regconfig, text)")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_page_chunks_text_fts", table_name="page_chunks")
