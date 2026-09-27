"""Small helpers that build and flush rows, so tests read as scenarios."""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import BrowsingEvent, Device, Page, PageChunk, PageChunkEmbedding, User
from app.schemas.capture import CaptureRequest

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_settings(**overrides: object) -> Settings:
    """Settings that need no environment and point at an unreachable database (127.0.0.1:1)."""
    values: dict[str, object] = {
        "environment": "test",
        "postgres_host": "127.0.0.1",
        "postgres_port": 1,
        "postgres_db": "apogee",
        "postgres_user": "apogee",
        "postgres_password": "unit-test-secret",
        "db_connect_timeout_seconds": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def make_user(session: Session) -> User:
    user = User()
    session.add(user)
    session.flush()
    return user


def make_device(session: Session, user: User, label: str = "laptop") -> Device:
    device = Device(user_id=user.id, label=label)
    session.add(device)
    session.flush()
    return device


def make_page(
    session: Session,
    user: User,
    url: str = "https://example.com/article",
    *,
    title: str | None = "An article",
    seen_at: datetime = T0,
) -> Page:
    page = Page(
        user_id=user.id,
        url=url,
        canonical_url=url,
        title=title,
        domain=urlsplit(url).hostname or "",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    session.add(page)
    session.flush()
    return page


def make_page_chunk(
    session: Session,
    page: Page,
    text: str = "A useful page passage.",
    *,
    chunk_index: int = 0,
) -> PageChunk:
    chunk = PageChunk(
        page_id=page.id,
        chunk_index=chunk_index,
        text=text,
        char_start=0,
        char_end=len(text),
    )
    session.add(chunk)
    session.flush()
    return chunk


def make_page_chunk_embedding(
    session: Session,
    user: User,
    page: Page,
    chunk: PageChunk,
    embedding: list[float],
    *,
    model_id: str = "test/model-v1",
) -> PageChunkEmbedding:
    row = PageChunkEmbedding(
        page_chunk_id=chunk.id,
        page_id=page.id,
        user_id=user.id,
        embedding_model=model_id,
        embedding_dimension=len(embedding),
        embedding=embedding,
    )
    session.add(row)
    session.flush()
    return row


def make_event(
    session: Session,
    user: User,
    device: Device,
    *,
    url: str = "https://example.com/article",
    page: Page | None = None,
    at: datetime = T0,
    session_id: uuid.UUID | None = None,
) -> BrowsingEvent:
    event = BrowsingEvent(
        user_id=user.id,
        device_id=device.id,
        page_id=page.id if page else None,
        url=url,
        title="A title",
        domain=urlsplit(url).hostname or "",
        occurred_at=at,
        session_id=session_id,
    )
    session.add(event)
    session.flush()
    return event


def hours(n: int) -> timedelta:
    return timedelta(hours=n)


def count(session: Session, model: type, **filters: object) -> int:
    statement = select(func.count()).select_from(model)
    for column, value in filters.items():
        statement = statement.where(getattr(model, column) == value)
    return session.scalar(statement) or 0


def make_capture_request(
    user: User,
    device: Device,
    url: str = "https://example.com/article",
    *,
    title: str | None = "An article",
    at: datetime = T0,
    session_id: uuid.UUID | None = None,
    content: str | None = None,
) -> CaptureRequest:
    return CaptureRequest(
        user_id=user.id,
        device_id=device.id,
        url=url,
        title=title,
        occurred_at=at,
        session_id=session_id,
        content=content,
    )
