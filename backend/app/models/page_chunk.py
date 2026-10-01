"""PageChunk: a deterministic slice of a page's cleaned text, produced at capture time."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PageChunk(Base):
    """One deterministic, fixed-size slice of a page's cleaned visible text.

    Produced by ``app.core.content.chunk_text`` at capture time and written by
    ``app.services.ingestion``. A page's chunks are replaced as a whole on every capture that
    includes content (see ``ingestion._replace_chunks``); the current chunks are embedded
    asynchronously after the capture transaction commits.
    """

    __tablename__ = "page_chunks"
    __table_args__ = (
        UniqueConstraint("page_id", "chunk_index", name="uq_page_chunks_page_id_chunk_index"),
        UniqueConstraint("id", "page_id", name="uq_page_chunks_id_page_id"),
        CheckConstraint("char_end > char_start", name="ck_page_chunks_char_end_after_char_start"),
        CheckConstraint("chunk_index >= 0", name="ck_page_chunks_chunk_index_non_negative"),
        Index("ix_page_chunks_page_id", "page_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # A chunk is entirely owned by its page (ON DELETE CASCADE). No user_id is denormalised here,
    # unlike browsing_events: nothing queries chunks by user directly yet, and a chunk can only
    # ever be reached through its page, which already belongs to exactly one user.
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))

    chunk_index: Mapped[int] = mapped_column(Integer)  # 0-based, stable ordering within the page
    text: Mapped[str] = mapped_column(Text)
    # Character offsets into the *cleaned* text this chunk was cut from (app.core.content output,
    # not the raw captured text). Kept for future debugging/re-chunking; nothing reads them yet.
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
