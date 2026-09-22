"""Browsing-event ingestion.

    CaptureRequest -> normalise URL -> check device ownership -> upsert page -> insert event -> commit

The page and the event are written in ONE transaction: afterwards either both exist or neither
does. Page identity is (user_id, canonical_url) and is enforced by the database's unique
constraint; concurrent captures of the same page are resolved by PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE``, never by Python-side locking.

This module owns the transaction: it commits on success and rolls back on any failure.
"""

import logging
import uuid

from sqlalchemy import Row, case, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.urls import extract_domain, normalize_url
from app.models import BrowsingEvent, Device, Page
from app.schemas.capture import CaptureRequest, CaptureResponse

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Base class for expected ingestion failures. Messages are safe to show to clients."""


class DeviceNotFoundError(IngestionError):
    """No device with this id exists for this user (unknown user, unknown device, or not theirs)."""


class IngestionConflictError(IngestionError):
    """The database rejected the write for a reason validation could not foresee (e.g. a race)."""


def ingest_browsing_event(session: Session, request: CaptureRequest) -> CaptureResponse:
    """Record one browsing event, creating or reusing its page. Commits on success."""
    canonical_url = normalize_url(request.url)
    domain = extract_domain(canonical_url)

    try:
        _require_device(session, request)
        page = _upsert_page(session, request, canonical_url, domain)
        event_id = _insert_event(session, request, page.id, canonical_url, domain)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # Log the constraint only: the exception text can include the offending key values.
        logger.warning("Integrity error while ingesting an event (constraint=%s)", _constraint(exc))
        raise IngestionConflictError("The event could not be stored because of a data conflict.") from None
    except Exception:
        session.rollback()
        raise

    # Deliberately IDs and a flag only: never the URL, which may contain sensitive query values.
    logger.info("Captured event %s for page %s (page_created=%s)", event_id, page.id, page.created)
    return CaptureResponse(
        event_id=event_id,
        page_id=page.id,
        page_created=page.created,
        canonical_url=canonical_url,
        domain=domain,
        title=page.title,
        first_seen_at=page.first_seen_at,
        last_seen_at=page.last_seen_at,
        occurred_at=request.occurred_at,
    )


def _require_device(session: Session, request: CaptureRequest) -> None:
    found = session.scalar(
        select(Device.id).where(Device.id == request.device_id, Device.user_id == request.user_id)
    )
    if found is None:
        # One error for "no such user", "no such device" and "someone else's device", so the
        # response does not reveal which ids exist.
        raise DeviceNotFoundError("No such device for this user.")


def _upsert_page(session: Session, request: CaptureRequest, canonical_url: str, domain: str) -> Row:
    """Insert the page, or on conflict update it, in a single atomic statement.

    ``xmax = 0`` in RETURNING is the standard PostgreSQL idiom for "this row was inserted rather
    than updated" (an implementation detail of ON CONFLICT DO UPDATE, stable for many releases).
    """
    insert_stmt = pg_insert(Page).values(
        user_id=request.user_id,
        url=canonical_url,  # the first observed URL, already stripped of fragment/tracking noise
        canonical_url=canonical_url,
        title=request.title,
        domain=domain,
        first_seen_at=request.occurred_at,
        last_seen_at=request.occurred_at,
    )
    incoming = insert_stmt.excluded
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["user_id", "canonical_url"],  # infers the unique (user_id, canonical_url) key
        set_={
            # Events can arrive out of order (a device syncing late), so widen the range.
            "first_seen_at": func.least(Page.first_seen_at, incoming.first_seen_at),
            "last_seen_at": func.greatest(Page.last_seen_at, incoming.last_seen_at),
            # The title follows the most recent visit; a missing title never erases a known one.
            "title": case(
                (incoming.title.is_(None), Page.title),
                (Page.title.is_(None), incoming.title),
                (incoming.last_seen_at >= Page.last_seen_at, incoming.title),
                else_=Page.title,
            ),
            "updated_at": func.now(),  # ORM onupdate hooks do not run for ON CONFLICT
        },
    ).returning(
        Page.id,
        Page.title,
        Page.first_seen_at,
        Page.last_seen_at,
        literal_column("(xmax = 0)").label("created"),
    )
    return session.execute(upsert_stmt).one()


def _insert_event(
    session: Session, request: CaptureRequest, page_id: uuid.UUID, canonical_url: str, domain: str
) -> uuid.UUID:
    event = BrowsingEvent(
        user_id=request.user_id,
        device_id=request.device_id,
        page_id=page_id,
        url=canonical_url,  # the raw URL is never stored
        title=request.title,
        domain=domain,
        occurred_at=request.occurred_at,
        session_id=request.session_id,
    )
    session.add(event)
    session.flush()  # surfaces constraint violations here, inside the try block
    return event.id


def _constraint(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
