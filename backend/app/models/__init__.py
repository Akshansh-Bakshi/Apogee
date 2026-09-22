"""Importing this package registers every model on ``Base.metadata`` (Alembic relies on it)."""

from app.models.browsing_event import BrowsingEvent
from app.models.device import Device
from app.models.page import Page
from app.models.user import User

__all__ = ["BrowsingEvent", "Device", "Page", "User"]
