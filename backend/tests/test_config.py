import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings
from tests.factories import make_settings

DB_ENV_VARS = ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]


def test_settings_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "mydb")
    monkeypatch.setenv("POSTGRES_USER", "me")
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-the-environment")

    settings = Settings(_env_file=None)

    url = settings.sqlalchemy_url
    assert (url.host, url.port, url.database, url.username) == ("db.internal", 6543, "mydb", "me")
    assert url.password == "from-the-environment"


def test_missing_database_settings_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DB_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert {"postgres_db", "postgres_user", "postgres_password"} <= missing


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(postgres_password="")


def test_password_with_special_characters_round_trips_through_the_url() -> None:
    password = "p@ss:w/rd%20#?"
    settings = make_settings(postgres_password=password)

    rendered = settings.sqlalchemy_url.render_as_string(hide_password=False)

    assert make_url(rendered).password == password
    assert make_url(rendered).host == "127.0.0.1"


def test_password_is_not_exposed_by_repr_or_str() -> None:
    settings = make_settings(postgres_password="unit-test-secret")

    assert "unit-test-secret" not in repr(settings)
    assert "unit-test-secret" not in str(settings.sqlalchemy_url)
