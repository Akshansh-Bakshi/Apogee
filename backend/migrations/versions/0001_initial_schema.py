"""Initial schema: users, devices, pages, browsing_events; enable pgvector.

Revision ID: 0001
Revises:
Create Date: 2026-09-19

Requires PostgreSQL 13+ (built-in gen_random_uuid()) and the pgvector extension to be available
on the server (the pgvector/pgvector Docker image provides it).

No vector column is created here on purpose: the embedding model, and therefore the vector
dimensionality, has not been chosen yet. See docs/architecture.md ("Vector storage").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_DEFAULT = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- users -------------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )

    # ---- devices -----------------------------------------------------------------------------
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_devices_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_devices_id_user_id"),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])

    # ---- pages -------------------------------------------------------------------------------
    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pages"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_pages_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "canonical_url", name="uq_pages_user_id_canonical_url"),
        sa.UniqueConstraint("id", "user_id", name="uq_pages_id_user_id"),
    )
    op.create_index("ix_pages_user_id_domain", "pages", ["user_id", "domain"])
    op.create_index("ix_pages_user_id_last_seen_at", "pages", ["user_id", "last_seen_at"])

    # ---- browsing_events ---------------------------------------------------------------------
    op.create_table(
        "browsing_events",
        sa.Column("id", sa.Uuid(), server_default=UUID_DEFAULT, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_browsing_events"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_browsing_events_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["device_id", "user_id"],
            ["devices.id", "devices.user_id"],
            name="fk_browsing_events_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "user_id"],
            ["pages.id", "pages.user_id"],
            name="fk_browsing_events_page_id_pages",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_browsing_events_user_id_occurred_at", "browsing_events", ["user_id", "occurred_at"]
    )
    op.create_index(
        "ix_browsing_events_device_id_occurred_at", "browsing_events", ["device_id", "occurred_at"]
    )
    op.create_index(
        "ix_browsing_events_user_id_domain_occurred_at",
        "browsing_events",
        ["user_id", "domain", "occurred_at"],
    )
    op.create_index("ix_browsing_events_page_id", "browsing_events", ["page_id"])
    op.create_index(
        "ix_browsing_events_user_id_session_id", "browsing_events", ["user_id", "session_id"]
    )


def downgrade() -> None:
    # Dropping a table drops its indexes and constraints. The pgvector extension is deliberately
    # left installed: it may pre-date this migration or be used by other objects in the database.
    op.drop_table("browsing_events")
    op.drop_table("pages")
    op.drop_table("devices")
    op.drop_table("users")
