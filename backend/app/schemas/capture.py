"""API contract for POST /api/v1/capture. Deliberately separate from the ORM models."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.core.urls import normalize_url

MAX_RAW_URL_LENGTH = 8192  # the canonical form is bounded separately (see normalize_url)
MAX_TITLE_LENGTH = 1024

# Guard rails for the client-supplied timestamp. pages.first_seen_at / last_seen_at are derived
# with LEAST/GREATEST, so one bogus value (epoch 0, year 2099) would otherwise pin them forever.
MIN_OCCURRED_AT = datetime(2000, 1, 1, tzinfo=UTC)
MAX_CLOCK_SKEW = timedelta(minutes=5)


class CaptureRequest(BaseModel):
    """One observed browser event.

    Only these fields are accepted. ``extra="forbid"`` turns any other key (cookies, passwords,
    tokens, form values, browser storage, ...) into a validation error instead of ignoring it, so
    a misbehaving client finds out and the server never has to decide what to do with such data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    device_id: UUID
    url: str = Field(min_length=1, max_length=MAX_RAW_URL_LENGTH)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    occurred_at: AwareDatetime  # timezone required: a naive timestamp is ambiguous
    session_id: UUID | None = None

    @field_validator("url")
    @classmethod
    def _url_must_be_capturable(cls, value: str) -> str:
        normalize_url(value)  # raises InvalidUrlError (a ValueError); its message never echoes the URL
        return value

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\x00" in value:
            raise ValueError("title must not contain NUL characters")
        return " ".join(value.split()) or None  # collapse whitespace; blank means "no title"

    @field_validator("occurred_at")
    @classmethod
    def _timestamp_must_be_plausible(cls, value: datetime) -> datetime:
        if value < MIN_OCCURRED_AT:
            raise ValueError("occurred_at must not be before 2000-01-01")
        if value > datetime.now(UTC) + MAX_CLOCK_SKEW:
            raise ValueError("occurred_at must not be in the future")
        return value


class CaptureResponse(BaseModel):
    event_id: UUID
    page_id: UUID
    page_created: bool  # False when an existing page was reused
    canonical_url: str
    domain: str
    title: str | None  # the page's current title (may come from an earlier visit)
    first_seen_at: datetime
    last_seen_at: datetime
    occurred_at: datetime
