"""POST /api/v1/capture through the real FastAPI application."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Sequence

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.models import BrowsingEvent, Page, PageChunk, PageChunkEmbedding, User
from app.services.embeddings import EmbeddingRole
from app.services.ingestion import IngestionConflictError
from tests.factories import count, make_device, make_settings, make_user

ENDPOINT = "/api/v1/capture"
FIRST_VISIT = "https://example.com/tutorial?id=42&utm_source=google#section1"
SECOND_VISIT = "https://example.com/tutorial?id=42&utm_source=twitter#section2"
CANONICAL = "https://example.com/tutorial?id=42"

RESPONSE_FIELDS = {
    "event_id", "page_id", "page_created", "canonical_url", "domain",
    "title", "first_seen_at", "last_seen_at", "occurred_at",
    "content_processed", "chunk_count",
}  # fmt: skip


@dataclass(frozen=True)
class Owner:
    user_id: uuid.UUID
    device_id: uuid.UUID


def instant(value: str) -> datetime:
    """Parse an ISO timestamp. Compare instants, not strings: PostgreSQL returns timestamptz in the
    server's configured time zone, so the same instant can be rendered with different offsets."""
    return datetime.fromisoformat(value)


def body(owner: Owner, url: str = FIRST_VISIT, **overrides: object) -> dict[str, object]:
    return {
        "user_id": str(owner.user_id),
        "device_id": str(owner.device_id),
        "url": url,
        "title": "Tutorial",
        "occurred_at": "2026-01-01T12:00:00Z",
        **overrides,
    }


class FakeEncoder:
    dimension = 384

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.calls: list[list[str]] = []
        self.fail = False

    def encode_text(self, text: str, *, role: EmbeddingRole = "passage") -> list[float]:
        return self.encode_batch([text], role=role)[0]

    def encode_batch(
        self, texts: Sequence[str], *, role: EmbeddingRole = "passage"
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("sensitive page text from test")
        return [[1.0] + [0.0] * 383 for _ in texts]


# --- fixtures ---------------------------------------------------------------------------------


@pytest.fixture
def offline_client() -> Iterator[TestClient]:
    """App whose database is unreachable: fine for anything rejected before the database is used."""
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def stranger() -> Owner:
    return Owner(uuid.uuid4(), uuid.uuid4())


@pytest.fixture
def client(migrated_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(migrated_settings), raise_server_exceptions=False) as test_client:
        test_client.app.state.embedding_encoder = FakeEncoder(migrated_settings.embedding_model_id)
        yield test_client


@pytest.fixture
def make_owner(engine: Engine) -> Iterator[Callable[[], Owner]]:
    """Creates committed users with a device (the API uses its own connection, so the rows must be
    committed) and deletes them, with everything they own, afterwards."""
    factory = sessionmaker(bind=engine)
    created: list[uuid.UUID] = []

    def create() -> Owner:
        with factory() as session:
            user = make_user(session)
            device = make_device(session, user, "test device")
            session.commit()
            created.append(user.id)
            return Owner(user.id, device.id)

    yield create

    with factory() as session:
        session.execute(delete(User).where(User.id.in_(created)))
        session.commit()


def rows(engine: Engine, model: type, **filters: object) -> int:
    with sessionmaker(bind=engine)() as session:
        return count(session, model, **filters)


# --- validation (never reaches the database) --------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "ftp://example.com/file"},
        {"url": "javascript:alert(1)"},
        {"url": "not a url"},
        {"url": "https://user:hunter2@example.com/"},  # credentials embedded in the URL
        {"url": ""},
        {"user_id": "not-a-uuid"},
        {"device_id": 12345},
        {"session_id": "nope"},
        {"occurred_at": "yesterday"},
        {"occurred_at": "2026-01-01T12:00:00"},  # naive timestamp
        {"occurred_at": "2999-01-01T00:00:00Z"},  # future
        {"title": "x" * 5000},
        {"cookies": "sid=hunter2"},
        {"password": "hunter2"},
        {"authorization": "Bearer hunter2"},
        {"form_values": {"card": "hunter2"}},
        {"local_storage": {"token": "hunter2"}},
    ],
)
def test_invalid_requests_get_a_safe_422(offline_client: TestClient, stranger: Owner, overrides: dict) -> None:
    response = offline_client.post(ENDPOINT, json=body(stranger, **overrides))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]  # says where and why...
    assert all(set(detail) == {"loc", "msg", "type"} for detail in error["details"])
    assert "hunter2" not in response.text  # ...but never echoes what the client sent


@pytest.mark.parametrize("field", ["user_id", "device_id", "url", "occurred_at"])
def test_a_missing_required_field_gets_a_422(offline_client: TestClient, stranger: Owner, field: str) -> None:
    payload = body(stranger)
    del payload[field]

    response = offline_client.post(ENDPOINT, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", field]


def test_a_malformed_json_body_gets_a_422(offline_client: TestClient) -> None:
    response = offline_client.post(ENDPOINT, content="{not json", headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- safe handling of server-side failures (no database needed) -------------------------------


def test_a_database_outage_is_a_503_that_reveals_nothing(offline_client: TestClient, stranger: Owner) -> None:
    response = offline_client.post(ENDPOINT, json=body(stranger))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    for leaked in ("unit-test-secret", "127.0.0.1", "postgres", "SELECT", "Traceback"):
        assert leaked not in response.text


def test_an_unexpected_error_is_a_generic_500(
    offline_client: TestClient, stranger: Owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SELECT * FROM users WHERE password='hunter2'")

    monkeypatch.setattr("app.api.v1.capture.ingest_browsing_event", explode)

    response = offline_client.post(ENDPOINT, json=body(stranger))

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "An unexpected error occurred."}}
    assert "hunter2" not in response.text and "SELECT" not in response.text


def test_a_data_conflict_is_a_409(
    offline_client: TestClient, stranger: Owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def conflict(*args: object, **kwargs: object) -> None:
        raise IngestionConflictError("constraint fk_browsing_events_device_id_devices violated")

    monkeypatch.setattr("app.api.v1.capture.ingest_browsing_event", conflict)

    response = offline_client.post(ENDPOINT, json=body(stranger))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "fk_browsing_events" not in response.text  # internal detail is not passed on


# --- ingestion through the API (real PostgreSQL) ----------------------------------------------


@pytest.mark.db
def test_a_capture_creates_a_page_and_an_event(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()

    response = client.post(ENDPOINT, json=body(owner))

    assert response.status_code == 201
    result = response.json()
    assert set(result) == RESPONSE_FIELDS
    assert result["page_created"] is True
    assert result["canonical_url"] == CANONICAL
    assert result["domain"] == "example.com"
    assert result["title"] == "Tutorial"
    assert instant(result["occurred_at"]) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    uuid.UUID(result["page_id"])
    uuid.UUID(result["event_id"])
    assert rows(engine, Page, user_id=owner.user_id) == 1
    assert rows(engine, BrowsingEvent, user_id=owner.user_id) == 1


@pytest.mark.db
def test_a_repeated_capture_reuses_the_page_and_adds_an_event(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()

    first = client.post(ENDPOINT, json=body(owner, FIRST_VISIT, occurred_at="2026-01-01T12:00:00Z"))
    second = client.post(ENDPOINT, json=body(owner, SECOND_VISIT, occurred_at="2026-01-02T09:30:00Z"))

    assert (first.status_code, second.status_code) == (201, 201)  # each one creates an event
    assert second.json()["page_id"] == first.json()["page_id"]
    assert second.json()["event_id"] != first.json()["event_id"]
    assert (first.json()["page_created"], second.json()["page_created"]) == (True, False)
    assert second.json()["canonical_url"] == first.json()["canonical_url"] == CANONICAL
    assert instant(second.json()["first_seen_at"]) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert instant(second.json()["last_seen_at"]) == datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    assert rows(engine, Page, user_id=owner.user_id) == 1
    assert rows(engine, BrowsingEvent, user_id=owner.user_id) == 2


@pytest.mark.db
def test_two_users_capturing_the_same_url_get_separate_pages(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    alice, bob = make_owner(), make_owner()

    a = client.post(ENDPOINT, json=body(alice)).json()
    b = client.post(ENDPOINT, json=body(bob)).json()

    assert a["page_id"] != b["page_id"]
    assert a["page_created"] is True and b["page_created"] is True
    assert rows(engine, Page, user_id=alice.user_id) == 1
    assert rows(engine, Page, user_id=bob.user_id) == 1


@pytest.mark.db
def test_a_session_id_is_accepted_and_stored(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()
    session_id = uuid.uuid4()

    response = client.post(ENDPOINT, json=body(owner, session_id=str(session_id)))

    assert response.status_code == 201
    assert rows(engine, BrowsingEvent, user_id=owner.user_id, session_id=session_id) == 1


@pytest.mark.db
def test_an_unknown_device_gets_a_404_and_writes_nothing(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()

    response = client.post(ENDPOINT, json=body(Owner(owner.user_id, uuid.uuid4())))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "device_not_found"
    assert rows(engine, Page, user_id=owner.user_id) == 0
    assert rows(engine, BrowsingEvent, user_id=owner.user_id) == 0


@pytest.mark.db
def test_another_users_device_gets_a_404_and_writes_nothing(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    alice, bob = make_owner(), make_owner()

    response = client.post(ENDPOINT, json=body(Owner(alice.user_id, bob.device_id)))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "device_not_found"
    for user_id in (alice.user_id, bob.user_id):
        assert rows(engine, Page, user_id=user_id) == 0
        assert rows(engine, BrowsingEvent, user_id=user_id) == 0


@pytest.mark.db
def test_a_rejected_request_writes_nothing(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()

    response = client.post(ENDPOINT, json=body(owner, url="ftp://example.com/x"))

    assert response.status_code == 422
    assert rows(engine, Page, user_id=owner.user_id) == 0
    assert rows(engine, BrowsingEvent, user_id=owner.user_id) == 0


@pytest.mark.db
def test_a_capture_with_content_is_cleaned_and_chunked(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()
    content = "This paragraph of visible page text is long enough to survive cleaning easily. " * 5

    response = client.post(ENDPOINT, json=body(owner, content=content))

    assert response.status_code == 201
    result = response.json()
    assert result["content_processed"] is True
    assert result["chunk_count"] >= 1
    assert rows(engine, PageChunk, page_id=uuid.UUID(result["page_id"])) == result["chunk_count"]


@pytest.mark.db
def test_a_capture_schedules_embedding_after_chunks_are_committed(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_owner()
    observed: list[tuple[uuid.UUID, int, object]] = []

    def observe(factory: sessionmaker[Session], page_id: uuid.UUID, encoder: object) -> None:
        with factory() as session:
            observed.append((page_id, count(session, PageChunk, page_id=page_id), encoder))

    monkeypatch.setattr("app.api.v1.capture.embed_page_after_capture", observe)
    response = client.post(ENDPOINT, json=body(owner, content="A useful article paragraph. " * 8))

    assert response.status_code == 201
    assert len(observed) == 1
    page_id, committed_chunks, encoder = observed[0]
    assert page_id == uuid.UUID(response.json()["page_id"])
    assert committed_chunks == response.json()["chunk_count"]
    assert encoder is client.app.state.embedding_encoder


@pytest.mark.db
def test_capture_background_embedding_persists_configured_384_dimensional_vectors(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()
    response = client.post(ENDPOINT, json=body(owner, content="A useful article paragraph. " * 8))
    page_id = uuid.UUID(response.json()["page_id"])

    with sessionmaker(bind=engine)() as session:
        chunks = session.scalars(select(PageChunk).where(PageChunk.page_id == page_id)).all()
        embeddings = session.scalars(
            select(PageChunkEmbedding).where(PageChunkEmbedding.page_id == page_id)
        ).all()

    assert response.status_code == 201
    assert len(embeddings) == len(chunks) == response.json()["chunk_count"]
    assert {row.page_chunk_id for row in embeddings} == {chunk.id for chunk in chunks}
    assert {row.embedding_model for row in embeddings} == {
        client.app.state.settings.embedding_model_id
    }
    assert {row.embedding_dimension for row in embeddings} == {384}


@pytest.mark.db
def test_embedding_failure_does_not_undo_committed_capture_or_log_page_contents(
    client: TestClient,
    engine: Engine,
    make_owner: Callable[[], Owner],
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = make_owner()
    text = "PRIVATE CONTENT SHOULD NOT APPEAR IN LOGS " * 4
    encoder = client.app.state.embedding_encoder
    encoder.fail = True

    response = client.post(ENDPOINT, json=body(owner, content=text))

    assert response.status_code == 201
    page_id = uuid.UUID(response.json()["page_id"])
    assert rows(engine, Page, user_id=owner.user_id) == 1
    assert rows(engine, BrowsingEvent, user_id=owner.user_id) == 1
    assert rows(engine, PageChunk, page_id=page_id) == response.json()["chunk_count"]
    assert rows(engine, PageChunkEmbedding, page_id=page_id) == 0
    assert "PRIVATE CONTENT SHOULD NOT APPEAR" not in caplog.text


@pytest.mark.db
def test_recapture_replaces_chunks_and_cascades_old_embeddings(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()
    first = client.post(ENDPOINT, json=body(owner, content="First captured paragraph. " * 8)).json()
    page_id = uuid.UUID(first["page_id"])
    with sessionmaker(bind=engine)() as session:
        old_chunk_ids = set(
            session.scalars(select(PageChunk.id).where(PageChunk.page_id == page_id)).all()
        )

    second_response = client.post(
        ENDPOINT,
        json=body(owner, occurred_at="2026-01-02T12:00:00Z", content="Replacement page content only. " * 8),
    )
    second = second_response.json()
    with sessionmaker(bind=engine)() as session:
        current_chunk_ids = set(
            session.scalars(select(PageChunk.id).where(PageChunk.page_id == page_id)).all()
        )
        embedded_chunk_ids = set(
            session.scalars(
                select(PageChunkEmbedding.page_chunk_id).where(PageChunkEmbedding.page_id == page_id)
            ).all()
        )

    assert second_response.status_code == 201
    assert second["page_id"] == first["page_id"]
    assert current_chunk_ids.isdisjoint(old_chunk_ids)
    assert embedded_chunk_ids == current_chunk_ids
    assert embedded_chunk_ids.isdisjoint(old_chunk_ids)


@pytest.mark.db
def test_a_capture_without_content_processes_nothing(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()

    response = client.post(ENDPOINT, json=body(owner))

    assert response.status_code == 201
    result = response.json()
    assert result["content_processed"] is False
    assert result["chunk_count"] == 0
    assert rows(engine, PageChunk, page_id=uuid.UUID(result["page_id"])) == 0


def test_near_empty_content_is_rejected_with_a_safe_422(offline_client: TestClient, stranger: Owner) -> None:
    response = offline_client.post(ENDPOINT, json=body(stranger, content="hi"))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", "content"]


@pytest.mark.db
def test_a_capture_rejected_for_its_content_writes_nothing(
    client: TestClient, engine: Engine, make_owner: Callable[[], Owner]
) -> None:
    owner = make_owner()

    response = client.post(ENDPOINT, json=body(owner, content="   "))

    assert response.status_code == 422
    assert rows(engine, Page, user_id=owner.user_id) == 0
    assert rows(engine, BrowsingEvent, user_id=owner.user_id) == 0
