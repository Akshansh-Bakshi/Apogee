from fastapi.testclient import TestClient

from app.main import create_app
from tests.factories import make_settings


def test_application_starts_and_stops_without_a_database() -> None:
    # The engine is created lazily, so startup must not require PostgreSQL.
    app = create_app(make_settings())

    with TestClient(app) as client:
        schema = client.get("/openapi.json")

        assert schema.status_code == 200
        assert {"/api/v1/health", "/api/v1/capture"} <= set(schema.json()["paths"])
        assert client.get("/does-not-exist").status_code == 404


def test_settings_are_carried_on_the_app_not_in_globals() -> None:
    first = create_app(make_settings(environment="development"))
    second = create_app(make_settings(environment="production"))

    assert first.state.settings.environment == "development"
    assert second.state.settings.environment == "production"
