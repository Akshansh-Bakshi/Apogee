"""The dashboard is served without requiring a database connection."""

import re

from fastapi.testclient import TestClient

from app.main import create_app
from tests.factories import make_settings


def test_dashboard_and_assets_are_available_without_a_database() -> None:
    with TestClient(create_app(make_settings())) as client:
        page = client.get("/app")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "default-src 'none'" in page.headers["content-security-policy"]
        assert not re.search(r'id="user-id"[^>]*\bvalue=', page.text)
        assert "id=\"search-form\"" in page.text
        for asset, content_type in [
            ("app.js", "javascript"),
            ("results.mjs", "javascript"),
            ("style.css", "text/css"),
        ]:
            response = client.get(f"/app/assets/{asset}")
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
