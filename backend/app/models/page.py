"""Page: the canonical document Apogee will eventually retrieve."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Page(Base):
    """One row per (user, canonical URL), no matter how often or from which device it is visited.

    Repeat visits are ``BrowsingEvent`` rows that point at the same ``Page``.
    """

    __tablename__ = "pages"
    __table_args__ = (
        # The de-duplication key: a user has at most one page per canonical URL.
        UniqueConstraint("user_id", "canonical_url", name="uq_pages_user_id_canonical_url"),
        # Lets browsing_events reference (page_id, user_id) so events can't cross users.
        UniqueConstraint("id", "user_id", name="uq_pages_id_user_id"),
        Index("ix_pages_user_id_domain", "user_id", "domain"),
        Index("ix_pages_user_id_last_seen_at", "user_id", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    # First observed URL, after normalisation (fragment and tracking parameters removed; the raw
    # URL is never stored). Today it equals canonical_url; the two can diverge once a canonical
    # URL is inferred from page content, which is future work.
    url: Mapped[str] = mapped_column(Text)
    # The dedup key, produced by app.core.urls.normalize_url. Bounded at 2048 chars so the unique
    # btree index entry stays well under PostgreSQL's ~2.7 kB limit; always percent-encoded ASCII.
    canonical_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(Text)
    # Lowercased hostname (max DNS length 253). Registrable-domain grouping is future work.
    domain: Mapped[str] = mapped_column(String(255))

    # Placeholder for text extracted from the page. Nothing writes to it yet.
    extracted_text: Mapped[str | None] = mapped_column(Text)

    # No server defaults: these come from event times (which may be older than the upload time
    # when a device syncs late), so the caller must always say what it means.
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
