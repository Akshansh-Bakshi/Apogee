"""Ingestion service against a real PostgreSQL database (no mocked persistence)."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import BrowsingEvent, Page, PageChunk, User
from app.schemas.capture import CaptureRequest, CaptureResponse
from app.services import ingestion
from app.services.ingestion import DeviceNotFoundError, ingest_browsing_event
from tests.factories import T0, count, hours, make_capture_request, make_device, make_user

pytestmark = pytest.mark.db

ARTICLE = "https://example.com/tutorial?id=42"


@pytest.fixture
def owner(db_session: Session):
    """A committed user + device. Committing here means a later rollback inside the service
    cannot undo this setup (it releases the SAVEPOINT the session opened for it)."""
    user = make_user(db_session)
    device = make_device(db_session, user, "laptop")
    db_session.commit()
    return user, device


def pages_of(session: Session, user: User) -> list[Page]:
    return list(session.scalars(select(Page).where(Page.user_id == user.id)))


def events_of(session: Session, user: User) -> list[BrowsingEvent]:
    return list(
        session.scalars(
            select(BrowsingEvent).where(BrowsingEvent.user_id == user.id).order_by(BrowsingEvent.occurred_at)
        )
    )


def chunks_of(session: Session, page: Page) -> list[PageChunk]:
    return list(
        session.scalars(
            select(PageChunk).where(PageChunk.page_id == page.id).order_by(PageChunk.chunk_index)
        )
    )


# --- page upsert: the five identity cases -----------------------------------------------------


def test_first_visit_creates_one_page_and_one_event(db_session: Session, owner) -> None:
    user, device = owner

    result = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE))

    assert result.page_created is True
    assert count(db_session, Page, user_id=user.id) == 1
    assert count(db_session, BrowsingEvent, user_id=user.id) == 1


def test_a_repeat_visit_reuses_the_page_and_adds_an_event(db_session: Session, owner) -> None:
    user, device = owner

    first = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, at=T0))
    second = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, at=T0 + hours(1)))

    assert second.page_id == first.page_id
    assert second.page_created is False
    assert second.event_id != first.event_id
    assert count(db_session, Page, user_id=user.id) == 1
    assert count(db_session, BrowsingEvent, user_id=user.id) == 2


def test_different_users_visiting_the_same_url_get_separate_pages(db_session: Session) -> None:
    alice, bob = make_user(db_session), make_user(db_session)
    alices_device, bobs_device = make_device(db_session, alice), make_device(db_session, bob)
    db_session.commit()

    a = ingest_browsing_event(db_session, make_capture_request(alice, alices_device, ARTICLE))
    b = ingest_browsing_event(db_session, make_capture_request(bob, bobs_device, ARTICLE))

    assert a.page_id != b.page_id
    assert a.page_created is True and b.page_created is True
    assert count(db_session, Page, user_id=alice.id) == 1
    assert count(db_session, Page, user_id=bob.id) == 1


def test_different_devices_of_one_user_share_one_page(db_session: Session, owner) -> None:
    user, laptop = owner
    phone = make_device(db_session, user, "phone")
    db_session.commit()

    ingest_browsing_event(db_session, make_capture_request(user, laptop, ARTICLE, at=T0))
    ingest_browsing_event(db_session, make_capture_request(user, phone, ARTICLE, at=T0 + hours(1)))
    ingest_browsing_event(db_session, make_capture_request(user, laptop, ARTICLE, at=T0 + hours(2)))

    assert count(db_session, Page, user_id=user.id) == 1
    assert count(db_session, BrowsingEvent, user_id=user.id) == 3
    assert {event.device_id for event in events_of(db_session, user)} == {laptop.id, phone.id}


def test_tracking_parameter_variants_share_one_page(db_session: Session, owner) -> None:
    user, device = owner
    urls = [
        "https://example.com/tutorial?id=42&utm_source=google#section1",
        "https://example.com/tutorial?id=42&utm_source=twitter#section2",
        "HTTPS://EXAMPLE.COM/tutorial?fbclid=abc&id=42",
    ]

    results = [
        ingest_browsing_event(db_session, make_capture_request(user, device, url, at=T0 + hours(i)))
        for i, url in enumerate(urls)
    ]

    assert len({result.page_id for result in results}) == 1
    assert [result.page_created for result in results] == [True, False, False]
    assert {result.canonical_url for result in results} == {ARTICLE}
    assert count(db_session, Page, user_id=user.id) == 1
    assert count(db_session, BrowsingEvent, user_id=user.id) == 3


def test_genuinely_different_pages_are_not_merged(db_session: Session, owner) -> None:
    user, device = owner

    ingest_browsing_event(db_session, make_capture_request(user, device, "https://example.com/a?id=1"))
    ingest_browsing_event(db_session, make_capture_request(user, device, "https://example.com/a?id=2"))
    ingest_browsing_event(db_session, make_capture_request(user, device, "https://example.com/b?id=1"))

    assert count(db_session, Page, user_id=user.id) == 3


# --- what gets stored -------------------------------------------------------------------------


def test_the_event_is_linked_to_its_page_and_stores_only_the_normalised_url(db_session: Session, owner) -> None:
    user, device = owner
    session_id = uuid.uuid4()
    raw = "https://Example.com:443/tutorial?id=42&utm_source=google#access_token=SECRET"

    result = ingest_browsing_event(
        db_session, make_capture_request(user, device, raw, title="A tutorial", at=T0, session_id=session_id)
    )

    (event,) = events_of(db_session, user)
    (page,) = pages_of(db_session, user)
    assert event.id == result.event_id
    assert event.page_id == page.id == result.page_id
    assert (event.user_id, event.device_id) == (user.id, device.id)
    assert event.url == page.url == page.canonical_url == ARTICLE
    assert event.domain == page.domain == "example.com"
    assert event.title == "A tutorial"
    assert event.occurred_at == T0
    assert event.session_id == session_id
    assert "SECRET" not in event.url + page.url + page.canonical_url  # fragment never persisted


def test_session_id_is_optional(db_session: Session, owner) -> None:
    user, device = owner
    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, at=T0, session_id=None))
    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, at=T0 + hours(1), session_id=uuid.uuid4()))

    with_none, with_id = events_of(db_session, user)
    assert with_none.session_id is None
    assert with_id.session_id is not None


def test_the_response_carries_canonical_metadata(db_session: Session, owner) -> None:
    user, device = owner

    result = ingest_browsing_event(
        db_session, make_capture_request(user, device, "https://Docs.Python.org/3/tutorial/?utm_source=x", title="Tutorial")
    )

    assert isinstance(result, CaptureResponse)
    assert result.canonical_url == "https://docs.python.org/3/tutorial/"
    assert result.domain == "docs.python.org"
    assert result.title == "Tutorial"
    assert result.first_seen_at == result.last_seen_at == result.occurred_at == T0


# --- page metadata over time ------------------------------------------------------------------


def test_the_seen_range_widens_even_when_events_arrive_out_of_order(db_session: Session, owner) -> None:
    user, device = owner

    for offset in (2, 0, 1):  # a device syncing late delivers older events after newer ones
        ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, at=T0 + hours(offset)))

    (page,) = pages_of(db_session, user)
    assert page.first_seen_at == T0
    assert page.last_seen_at == T0 + hours(2)


def test_the_title_follows_the_most_recent_visit(db_session: Session, owner) -> None:
    user, device = owner

    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, title="Old title", at=T0))
    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, title="New title", at=T0 + hours(2)))
    # A late-arriving OLDER event must not overwrite the newer title...
    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, title="Ancient", at=T0 - hours(5)))
    # ...and a visit without a title must not erase a known one.
    result = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, title=None, at=T0 + hours(3)))

    assert result.title == "New title"
    assert pages_of(db_session, user)[0].title == "New title"


def test_a_missing_title_is_filled_in_by_a_later_visit(db_session: Session, owner) -> None:
    user, device = owner

    first = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, title=None, at=T0))
    later = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, title="Now titled", at=T0 + hours(1)))

    assert first.title is None
    assert later.title == "Now titled"


def test_a_repeat_visit_updates_the_pages_updated_at_and_keeps_created_at(engine: Engine) -> None:
    # Committed transactions are needed: now() is fixed within one transaction.
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        user = make_user(session)
        device = make_device(session, user)
        session.commit()
        user_id = user.id
        try:
            ingest_browsing_event(session, make_capture_request(user, device, ARTICLE, at=T0))
            before = pages_of(session, user)[0]
            created_at, updated_at = before.created_at, before.updated_at
            session.expire_all()

            ingest_browsing_event(session, make_capture_request(user, device, ARTICLE, at=T0 + hours(1)))
            session.expire_all()
            after = pages_of(session, user)[0]

            assert after.created_at == created_at
            assert after.updated_at > updated_at
        finally:
            session.rollback()
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


# --- ownership --------------------------------------------------------------------------------


def test_an_unknown_device_is_rejected_and_nothing_is_written(db_session: Session, owner) -> None:
    user, _ = owner
    request = CaptureRequest(user_id=user.id, device_id=uuid.uuid4(), url=ARTICLE, occurred_at=T0)

    with pytest.raises(DeviceNotFoundError):
        ingest_browsing_event(db_session, request)

    assert count(db_session, Page, user_id=user.id) == 0
    assert count(db_session, BrowsingEvent, user_id=user.id) == 0


def test_an_unknown_user_is_rejected_and_nothing_is_written(db_session: Session, owner) -> None:
    _, device = owner
    ghost = uuid.uuid4()
    request = CaptureRequest(user_id=ghost, device_id=device.id, url=ARTICLE, occurred_at=T0)

    with pytest.raises(DeviceNotFoundError):
        ingest_browsing_event(db_session, request)

    assert count(db_session, Page, user_id=ghost) == 0
    assert count(db_session, BrowsingEvent, user_id=ghost) == 0
    assert count(db_session, BrowsingEvent, device_id=device.id) == 0


def test_a_device_belonging_to_another_user_is_rejected(db_session: Session) -> None:
    alice, bob = make_user(db_session), make_user(db_session)
    bobs_device = make_device(db_session, bob)
    db_session.commit()

    with pytest.raises(DeviceNotFoundError):
        ingest_browsing_event(db_session, make_capture_request(alice, bobs_device, ARTICLE))

    for user in (alice, bob):
        assert count(db_session, Page, user_id=user.id) == 0
        assert count(db_session, BrowsingEvent, user_id=user.id) == 0


# --- atomicity --------------------------------------------------------------------------------


def test_a_failure_after_the_page_upsert_leaves_no_partial_state(
    db_session: Session, owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, device = owner

    def explode(*args: object, **kwargs: object) -> uuid.UUID:
        raise RuntimeError("simulated failure while inserting the event")

    # The page upsert really executes against PostgreSQL; only the event insert is made to fail.
    monkeypatch.setattr(ingestion, "_insert_event", explode)

    with pytest.raises(RuntimeError):
        ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE))

    assert count(db_session, Page, user_id=user.id) == 0  # the page was rolled back too
    assert count(db_session, BrowsingEvent, user_id=user.id) == 0
    assert count(db_session, User, id=user.id) == 1  # setup outside the failed operation survives


def test_the_session_is_usable_after_a_failed_ingestion(db_session: Session, owner) -> None:
    user, device = owner
    with pytest.raises(DeviceNotFoundError):
        ingest_browsing_event(
            db_session, CaptureRequest(user_id=user.id, device_id=uuid.uuid4(), url=ARTICLE, occurred_at=T0)
        )

    result = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE))

    assert result.page_created is True


# --- concurrency ------------------------------------------------------------------------------


def test_concurrent_captures_of_one_page_create_exactly_one_page(engine: Engine) -> None:
    """Real threads, real connections, real commits: PostgreSQL's ON CONFLICT is what serialises them."""
    workers = 8
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as setup:
        user = make_user(setup)
        device = make_device(setup, user)
        setup.commit()
        user_id, device_id = user.id, device.id

    start_together = threading.Barrier(workers, timeout=30)

    def capture(worker: int) -> CaptureResponse:
        request = CaptureRequest(
            user_id=user_id,
            device_id=device_id,
            url=f"https://example.com/race?id=1&utm_source=worker{worker}",  # all normalise to one page
            occurred_at=T0 + timedelta(seconds=worker),
        )
        with factory() as session:
            start_together.wait()
            return ingest_browsing_event(session, request)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(capture, range(workers)))

        with factory() as check:
            assert count(check, Page, user_id=user_id) == 1
            assert count(check, BrowsingEvent, user_id=user_id) == workers
            (page,) = check.scalars(select(Page).where(Page.user_id == user_id))
            assert page.first_seen_at == T0
            assert page.last_seen_at == T0 + timedelta(seconds=workers - 1)

        assert len({result.page_id for result in results}) == 1
        assert len({result.event_id for result in results}) == workers
        assert sum(result.page_created for result in results) == 1  # exactly one insert won the race
    finally:
        with factory() as cleanup:
            cleanup.execute(delete(User).where(User.id == user_id))
            cleanup.commit()


# --- content processing / chunk persistence -------------------------------------------------------

SHORT_CONTENT = "x" * 500  # under the default chunk_size (1000): exactly one chunk
LONG_CONTENT = "x" * 2500  # over one chunk: exactly three chunks under the default size/overlap


def test_a_capture_without_content_processes_nothing(db_session: Session, owner) -> None:
    user, device = owner

    result = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, content=None))

    assert result.content_processed is False
    assert result.chunk_count == 0
    (page,) = pages_of(db_session, user)
    assert chunks_of(db_session, page) == []


def test_a_capture_with_content_cleans_chunks_and_persists_them(db_session: Session, owner) -> None:
    user, device = owner

    result = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, content=LONG_CONTENT))

    assert result.content_processed is True
    assert result.chunk_count == 3
    (page,) = pages_of(db_session, user)
    chunks = chunks_of(db_session, page)
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.page_id == page.id for c in chunks)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(LONG_CONTENT)
    assert all(c.text == LONG_CONTENT[c.char_start : c.char_end] for c in chunks)


def test_a_short_capture_produces_exactly_one_chunk(db_session: Session, owner) -> None:
    user, device = owner

    result = ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, content=SHORT_CONTENT))

    assert result.chunk_count == 1
    (page,) = pages_of(db_session, user)
    (chunk,) = chunks_of(db_session, page)
    assert chunk.text == SHORT_CONTENT


def test_recapturing_with_new_content_replaces_the_old_chunks(db_session: Session, owner) -> None:
    user, device = owner

    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, content=SHORT_CONTENT, at=T0))
    ingest_browsing_event(
        db_session, make_capture_request(user, device, ARTICLE, content=LONG_CONTENT, at=T0 + hours(1))
    )

    (page,) = pages_of(db_session, user)
    chunks = chunks_of(db_session, page)
    assert len(chunks) == 3  # LONG_CONTENT's shape, not SHORT_CONTENT's
    assert count(db_session, PageChunk, page_id=page.id) == 3  # nothing left over from the first capture


def test_recapturing_without_content_leaves_existing_chunks_untouched(db_session: Session, owner) -> None:
    user, device = owner

    ingest_browsing_event(db_session, make_capture_request(user, device, ARTICLE, content=SHORT_CONTENT, at=T0))
    result = ingest_browsing_event(
        db_session, make_capture_request(user, device, ARTICLE, content=None, at=T0 + hours(1))
    )

    assert result.content_processed is False
    (page,) = pages_of(db_session, user)
    (chunk,) = chunks_of(db_session, page)
    assert chunk.text == SHORT_CONTENT  # the earlier capture's chunk is still there


def test_chunks_are_only_reachable_through_their_own_page(db_session: Session) -> None:
    alice, bob = make_user(db_session), make_user(db_session)
    alices_device, bobs_device = make_device(db_session, alice), make_device(db_session, bob)
    db_session.commit()

    ingest_browsing_event(db_session, make_capture_request(alice, alices_device, ARTICLE, content=SHORT_CONTENT))
    ingest_browsing_event(db_session, make_capture_request(bob, bobs_device, ARTICLE, content=LONG_CONTENT))

    (alices_page,) = pages_of(db_session, alice)
    (bobs_page,) = pages_of(db_session, bob)
    assert {c.page_id for c in chunks_of(db_session, alices_page)} == {alices_page.id}
    assert {c.page_id for c in chunks_of(db_session, bobs_page)} == {bobs_page.id}


def test_a_failure_at_commit_rolls_back_the_page_event_and_chunks_together(
    db_session: Session, owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, device = owner
    original_commit = db_session.commit

    def explode() -> None:
        raise RuntimeError("simulated failure at commit time")

    monkeypatch.setattr(db_session, "commit", explode)
    try:
        with pytest.raises(RuntimeError):
            ingest_browsing_event(
                db_session, make_capture_request(user, device, ARTICLE, content=SHORT_CONTENT)
            )
    finally:
        monkeypatch.setattr(db_session, "commit", original_commit)

    assert count(db_session, Page, user_id=user.id) == 0
    assert count(db_session, PageChunk) == 0
