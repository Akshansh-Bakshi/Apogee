"""User: the owner of devices, pages and browsing events."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.device import Device


class User(Base):
    """Every row in the other tables is owned by exactly one user.

    Deleting a user cascades (in the database) to all of their devices, pages and events, which is
    the foundation for "delete all my data".
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # Deletion is enforced by the database (ON DELETE CASCADE); passive_deletes stops the ORM
    # from loading every child row just to delete it.
    devices: Mapped[list["Device"]] = relationship(
        back_populates="user", cascade="all", passive_deletes=True
    )
