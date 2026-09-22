"""Request validation for POST /api/v1/capture. No database needed."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.capture import MAX_TITLE_LENGTH, CaptureRequest

USER_ID = "6f1f7d2e-3b8a-4c55-9a1e-0d3f5a7b9c11"
DEVICE_ID = "0a9c1b2d-4e5f-4a6b-8c7d-1e2f3a4b5c6d"


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "user_id": USER_ID,
        "device_id": DEVICE_ID,
        "url": "https://example.com/tutorial?id=42&utm_source=google#section1",
        "title": "A tutorial",
        "occurred_at": "2026-01-01T12:00:00Z",
    }
    return {**base, **overrides}


def error_locations(excinfo: pytest.ExceptionInfo[ValidationError]) -> set[tuple[str | int, ...]]:
    return {error["loc"] for error in excinfo.value.errors()}


def test_a_valid_request_is_parsed_into_typed_fields() -> None:
    request = CaptureRequest(**payload())

    assert request.user_id == uuid.UUID(USER_ID)
    assert request.device_id == uuid.UUID(DEVICE_ID)
    assert request.occurred_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert request.title == "A tutorial"
    assert request.session_id is None  # optional
    assert request.url == "https://example.com/tutorial?id=42&utm_source=google#section1"  # raw input kept


def test_title_and_session_id_are_optional() -> None:
    session_id = uuid.uuid4()
    request = CaptureRequest(**payload(title=None, session_id=str(session_id)))

    assert request.title is None
    assert request.session_id == session_id


@pytest.mark.parametrize("field", ["user_id", "device_id", "session_id"])
@pytest.mark.parametrize("bad", ["not-a-uuid", "12345", "", 42])
def test_invalid_uuids_are_rejected(field: str, bad: object) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(**{field: bad}))

    assert error_locations(excinfo) == {(field,)}


@pytest.mark.parametrize("field", ["user_id", "device_id", "url", "occurred_at"])
def test_required_fields_are_required(field: str) -> None:
    data = payload()
    del data[field]

    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**data)

    assert error_locations(excinfo) == {(field,)}


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "not a url",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:hunter2@example.com/",
        "http://example.com:99999/",
        "https:///path",
        "x" * 9000,  # longer than the raw-URL limit
    ],
)
def test_invalid_urls_are_rejected(bad_url: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(url=bad_url))

    assert error_locations(excinfo) == {("url",)}


def test_url_error_messages_do_not_echo_the_url() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(url="https://user:hunter2@example.com/?token=abc123"))

    messages = " ".join(error["msg"] for error in excinfo.value.errors())
    assert "hunter2" not in messages
    assert "abc123" not in messages


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "yesterday",
        "",
        "2026-13-45T00:00:00Z",  # impossible date
        "2026-01-01T12:00:00",  # naive: no timezone
        "1999-12-31T23:59:59Z",  # implausibly old
        (datetime.now(UTC) + timedelta(days=1)).isoformat(),  # in the future
    ],
)
def test_invalid_timestamps_are_rejected(bad_timestamp: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(occurred_at=bad_timestamp))

    assert error_locations(excinfo) == {("occurred_at",)}


def test_a_timestamp_with_a_non_utc_offset_is_accepted() -> None:
    request = CaptureRequest(**payload(occurred_at="2026-01-01T17:30:00+05:30"))

    assert request.occurred_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # same instant


def test_a_title_at_the_limit_is_accepted_and_one_over_is_rejected() -> None:
    assert CaptureRequest(**payload(title="t" * MAX_TITLE_LENGTH)).title == "t" * MAX_TITLE_LENGTH

    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(title="t" * (MAX_TITLE_LENGTH + 1)))

    assert error_locations(excinfo) == {("title",)}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Spaced   out \n title\t", "Spaced out title"),  # whitespace collapsed
        ("", None),
        ("   \n ", None),  # blank means "no title"
    ],
)
def test_titles_are_cleaned(raw: str, expected: str | None) -> None:
    assert CaptureRequest(**payload(title=raw)).title == expected


def test_a_title_with_a_nul_character_is_rejected() -> None:
    # PostgreSQL text cannot hold NUL; catching it here avoids a database error later.
    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(title="bad\x00title"))

    assert error_locations(excinfo) == {("title",)}


@pytest.mark.parametrize(
    "extra",
    [
        {"cookies": "sid=abc123"},
        {"cookie": {"sid": "abc123"}},
        {"password": "hunter2"},
        {"authorization": "Bearer abc123"},
        {"auth_token": "abc123"},
        {"form_values": {"email": "a@b.c"}},
        {"local_storage": {"k": "v"}},
        {"page_text": "the whole page"},
    ],
)
def test_sensitive_or_unknown_fields_are_rejected_not_ignored(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as excinfo:
        CaptureRequest(**payload(**extra))

    assert {error["type"] for error in excinfo.value.errors()} == {"extra_forbidden"}


def test_requests_are_immutable() -> None:
    request = CaptureRequest(**payload())

    with pytest.raises(ValidationError):
        request.url = "https://elsewhere.example/"  # type: ignore[misc]
