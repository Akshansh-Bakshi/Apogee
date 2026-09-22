import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.db_utils import temporary_database
from tests.factories import make_settings


def test_health_reports_unavailable_when_the_database_is_unreachable() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "unavailable"
    assert body["database"]["status"] == "unavailable"
    assert body["application"]["name"] == "Apogee"
    assert body["application"]["environment"] == "test"
    # The response must not leak connection details or credentials.
    assert "unit-test-secret" not in response.text
    assert "127.0.0.1" not in response.text


@pytest.mark.db
def test_health_is_ok_against_a_migrated_database(migrated_settings: Settings) -> None:
    with TestClient(create_app(migrated_settings)) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert body["database"]["pgvector_version"]  # extension was enabled by the migration
    assert body["database"]["server_version"][0].isdigit()
    assert body["database"]["latency_ms"] >= 0


@pytest.mark.db
def test_health_is_degraded_when_migrations_have_not_been_applied(base_settings: Settings) -> None:
    # A brand-new database has no pgvector extension: connected, but not ready.
    with temporary_database(base_settings, migrate=False) as settings:
        with TestClient(create_app(settings)) as client:
            response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["database"]["pgvector_version"] is None
    assert "migrations" in body["database"]["detail"].lower()
