"""Device: one browser/machine belonging to a user."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        # Lets child tables reference (device_id, user_id), so an event can never point at a
        # device owned by a different user. See BrowsingEvent.
        UniqueConstraint("id", "user_id", name="uq_devices_id_user_id"),
        Index("ix_devices_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(255))  # user-facing name, e.g. "Work laptop"
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime | None]

    user: Mapped["User"] = relationship(back_populates="devices")
