"""Schema behaviour against a real PostgreSQL database built by the migrations."""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BrowsingEvent, Device, Page, User
from tests.factories import T0, count, hours, make_device, make_event, make_page, make_user

pytestmark = pytest.mark.db


# --- basic row behaviour ----------------------------------------------------------------------


def test_user_gets_a_generated_uuid_and_timestamps(db_session: Session) -> None:
    user = make_user(db_session)

    assert isinstance(user.id, uuid.UUID)
    assert user.created_at is not None
    assert user.updated_at is not None


def test_a_user_can_have_several_devices(db_session: Session) -> None:
    user = make_user(db_session)
    make_device(db_session, user, "work laptop")
    make_device(db_session, user, "phone")

    db_session.refresh(user)

    assert sorted(device.label for device in user.devices) == ["phone", "work laptop"]
    assert all(device.last_seen_at is None for device in user.devices)


def test_a_device_must_belong_to_an_existing_user(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Device(user_id=uuid.uuid4(), label="orphan"))
            db_session.flush()


def test_page_updated_at_advances_when_the_page_is_updated(engine: Engine) -> None:
    # Uses committed transactions: now() is fixed within a transaction, so the rolled-back
    # db_session fixture cannot observe a change.
    with Session(engine) as session:
        user = make_user(session)
        page = make_page(session, user)
        session.commit()
        user_id, first_updated_at = user.id, page.updated_at
        try:
            page.title = "A new title"
            session.commit()

            assert page.updated_at > first_updated_at
        finally:
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


# --- page de-duplication ----------------------------------------------------------------------


def test_a_user_has_one_page_per_canonical_url(db_session: Session) -> None:
    user = make_user(db_session)
    make_page(db_session, user, "https://example.com/a")

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_page(db_session, user, "https://example.com/a")


def test_different_users_can_have_the_same_canonical_url(db_session: Session) -> None:
    make_page(db_session, make_user(db_session), "https://example.com/a")
    make_page(db_session, make_user(db_session), "https://example.com/a")

    assert count(db_session, Page, canonical_url="https://example.com/a") == 2


def test_repeat_visits_from_several_devices_share_one_page(db_session: Session) -> None:
    user = make_user(db_session)
    laptop = make_device(db_session, user, "laptop")
    phone = make_device(db_session, user, "phone")
    page = make_page(db_session, user)

    make_event(db_session, user, laptop, page=page, at=T0)
    make_event(db_session, user, laptop, page=page, at=T0 + hours(1))
    make_event(db_session, user, phone, page=page, at=T0 + hours(2))

    assert count(db_session, Page, user_id=user.id) == 1
    assert count(db_session, BrowsingEvent, page_id=page.id) == 3


def test_an_event_does_not_require_a_page(db_session: Session) -> None:
    user = make_user(db_session)
    event = make_event(db_session, user, make_device(db_session, user), page=None)

    assert event.page_id is None


# --- ownership is enforced by the database ----------------------------------------------------


def test_an_event_cannot_use_another_users_device(db_session: Session) -> None:
    alice, bob = make_user(db_session), make_user(db_session)
    bobs_device = make_device(db_session, bob)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_event(db_session, alice, bobs_device)


def test_an_event_cannot_reference_another_users_page(db_session: Session) -> None:
    alice, bob = make_user(db_session), make_user(db_session)
    alices_device = make_device(db_session, alice)
    bobs_page = make_page(db_session, bob)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            make_event(db_session, alice, alices_device, page=bobs_page)


# --- the query patterns the schema must support -----------------------------------------------


@dataclass
class Activity:
    alice: User
    bob: User
    laptop: Device
    phone: Device
    pages: dict[str, Page]


@pytest.fixture
def activity(db_session: Session) -> Activity:
    """Alice: laptop + phone. Bob: one device. Events spread over hours and domains."""
    alice, bob = make_user(db_session), make_user(db_session)
    laptop = make_device(db_session, alice, "laptop")
    phone = make_device(db_session, alice, "phone")
    bobs_device = make_device(db_session, bob, "bob laptop")

    docs = "https://docs.python.org/3/library/uuid.html"
    news = "https://news.example.org/story"
    pages = {docs: make_page(db_session, alice, docs), news: make_page(db_session, alice, news)}
    make_page(db_session, bob, docs)  # same URL, different owner

    make_event(db_session, alice, laptop, url=docs, page=pages[docs], at=T0)
    make_event(db_session, alice, laptop, url=news, page=pages[news], at=T0 + hours(1))
    make_event(db_session, alice, phone, url=docs, page=pages[docs], at=T0 + hours(2))
    make_event(db_session, alice, phone, url=news, page=pages[news], at=T0 + hours(3))
    make_event(db_session, bob, bobs_device, url=docs, at=T0 + hours(1))
    return Activity(alice, bob, laptop, phone, pages)


def test_all_activity_for_a_user(db_session: Session, activity: Activity) -> None:
    rows = db_session.scalars(
        select(BrowsingEvent).where(BrowsingEvent.user_id == activity.alice.id)
    ).all()

    assert len(rows) == 4
    assert {row.user_id for row in rows} == {activity.alice.id}


def test_activity_from_one_device(db_session: Session, activity: Activity) -> None:
    rows = db_session.scalars(
        select(BrowsingEvent).where(BrowsingEvent.device_id == activity.phone.id)
    ).all()

    assert len(rows) == 2
    assert {row.device_id for row in rows} == {activity.phone.id}


def test_activity_within_a_time_range(db_session: Session, activity: Activity) -> None:
    rows = db_session.scalars(
        select(BrowsingEvent)
        .where(
            BrowsingEvent.user_id == activity.alice.id,
            BrowsingEvent.occurred_at >= T0 + hours(1),
            BrowsingEvent.occurred_at < T0 + hours(3),  # half-open range
        )
        .order_by(BrowsingEvent.occurred_at)
    ).all()

    assert [row.occurred_at for row in rows] == [T0 + hours(1), T0 + hours(2)]


def test_activity_for_a_domain(db_session: Session, activity: Activity) -> None:
    rows = db_session.scalars(
        select(BrowsingEvent).where(
            BrowsingEvent.user_id == activity.alice.id,
            BrowsingEvent.domain == "docs.python.org",
        )
    ).all()

    assert len(rows) == 2
    assert {row.url for row in rows} == {"https://docs.python.org/3/library/uuid.html"}


def test_pages_associated_with_a_user(db_session: Session, activity: Activity) -> None:
    urls = db_session.scalars(
        select(Page.canonical_url).where(Page.user_id == activity.alice.id).order_by(Page.domain)
    ).all()

    assert urls == [
        "https://docs.python.org/3/library/uuid.html",
        "https://news.example.org/story",
    ]


def test_session_grouping_is_available_for_temporal_queries(db_session: Session) -> None:
    user = make_user(db_session)
    device = make_device(db_session, user)
    session_id = uuid.uuid4()
    make_event(db_session, user, device, session_id=session_id, at=T0)
    make_event(db_session, user, device, session_id=session_id, at=T0 + hours(1))
    make_event(db_session, user, device, session_id=None, at=T0 + hours(2))

    assert count(db_session, BrowsingEvent, user_id=user.id, session_id=session_id) == 2


# --- deletion / privacy ------------------------------------------------------------------------


def test_deleting_a_user_removes_everything_they_own(db_session: Session, activity: Activity) -> None:
    db_session.execute(delete(User).where(User.id == activity.alice.id))

    assert count(db_session, Device, user_id=activity.alice.id) == 0
    assert count(db_session, Page, user_id=activity.alice.id) == 0
    assert count(db_session, BrowsingEvent, user_id=activity.alice.id) == 0
    # Another user's data is untouched.
    assert count(db_session, Device, user_id=activity.bob.id) == 1
    assert count(db_session, BrowsingEvent, user_id=activity.bob.id) == 1


def test_deleting_a_device_removes_only_its_events(db_session: Session, activity: Activity) -> None:
    db_session.execute(delete(Device).where(Device.id == activity.phone.id))

    assert count(db_session, BrowsingEvent, device_id=activity.phone.id) == 0
    assert count(db_session, BrowsingEvent, device_id=activity.laptop.id) == 2
    assert count(db_session, Page, user_id=activity.alice.id) == 2  # pages remain


def test_deleting_a_page_removes_the_events_that_reference_it(
    db_session: Session, activity: Activity
) -> None:
    docs_page = activity.pages["https://docs.python.org/3/library/uuid.html"]

    db_session.execute(delete(Page).where(Page.id == docs_page.id))

    assert count(db_session, BrowsingEvent, page_id=docs_page.id) == 0
    assert count(db_session, BrowsingEvent, user_id=activity.alice.id) == 2
