"""Shared fixtures.

Tests marked ``db`` need a running PostgreSQL server (with pgvector available) described by the
POSTGRES_* environment variables / .env file. Everything else runs with no external services.
"""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_db_engine
from tests.db_utils import temporary_database


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    """Server credentials for DB tests, taken from the environment (never hard-coded)."""
    try:
        return Settings()
    except ValidationError:
        pytest.fail(
            "Database settings are missing. Copy .env.example to .env (repo root) and set "
            "POSTGRES_PASSWORD, or export the POSTGRES_* variables. See README.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def migrated_settings(base_settings: Settings) -> Iterator[Settings]:
    """A throwaway database whose schema was built by `alembic upgrade head`."""
    with temporary_database(base_settings, migrate=True) as settings:
        yield settings


@pytest.fixture(scope="session")
def engine(migrated_settings: Settings) -> Iterator[Engine]:
    db_engine = create_db_engine(migrated_settings)
    yield db_engine
    db_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test.

    ``create_savepoint`` means even ``session.commit()`` / ``session.begin_nested()`` inside a test
    stay within the outer transaction, so tests are isolated and can still provoke IntegrityErrors.
    """
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()
