"""BrowsingEvent: one observed browser event (append-only log)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BrowsingEvent(Base):
    """What was observed, where, and when.

    Stores only URL, title and timestamps. There are intentionally no columns for cookies,
    credentials, tokens, form values or other browser state (see docs/privacy.md).
    """

    __tablename__ = "browsing_events"
    __table_args__ = (
        # user_id is denormalised onto the event so per-user queries need no join. These composite
        # foreign keys make the database enforce that the device and page belong to that same user.
        # Deleting a device or page deletes the events that reference it (nothing lingers).
        # page_id is nullable; with MATCH SIMPLE semantics its constraint is skipped when NULL.
        ForeignKeyConstraint(
            ["device_id", "user_id"],
            ["devices.id", "devices.user_id"],
            name="fk_browsing_events_device_id_devices",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["page_id", "user_id"],
            ["pages.id", "pages.user_id"],
            name="fk_browsing_events_page_id_pages",
            ondelete="CASCADE",
        ),
        Index("ix_browsing_events_user_id_occurred_at", "user_id", "occurred_at"),
        Index("ix_browsing_events_device_id_occurred_at", "device_id", "occurred_at"),
        Index("ix_browsing_events_user_id_domain_occurred_at", "user_id", "domain", "occurred_at"),
        Index("ix_browsing_events_page_id", "page_id"),
        Index("ix_browsing_events_user_id_session_id", "user_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID]  # constrained by the composite foreign key above
    page_id: Mapped[uuid.UUID | None]  # constrained by the composite foreign key above

    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))  # lowercased hostname

    # When the browser event happened (client clock). created_at is when Apogee stored it.
    occurred_at: Mapped[datetime]
    # Client-assigned session identifier. There is no sessions table yet, so no foreign key;
    # one can be added when session/temporal features arrive.
    session_id: Mapped[uuid.UUID | None]

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
