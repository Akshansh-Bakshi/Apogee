"""Helpers for tests that need a real PostgreSQL database.

Tests never touch the development database. They create a uniquely named throwaway database on
the same server (using the credentials from the environment), build its schema with Alembic, and
drop it afterwards.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config(settings: Settings) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy_url"] = settings.sqlalchemy_url
    config.attributes["configure_logger"] = False  # don't reconfigure pytest's logging
    return config


def upgrade(settings: Settings, revision: str = "head") -> None:
    command.upgrade(alembic_config(settings), revision)


def downgrade(settings: Settings, revision: str = "base") -> None:
    command.downgrade(alembic_config(settings), revision)


@contextmanager
def temporary_database(base: Settings, *, migrate: bool) -> Iterator[Settings]:
    """Create a fresh database, yield Settings pointing at it, and drop it on exit.

    With ``migrate=True`` the schema is built by running ``alembic upgrade head``; otherwise the
    database is left empty (no tables, no pgvector extension).
    """
    name = f"apogee_test_{uuid.uuid4().hex[:12]}"  # generated here, so safe to interpolate
    admin_engine = create_engine(
        base.sqlalchemy_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",  # CREATE/DROP DATABASE cannot run inside a transaction
        connect_args={"connect_timeout": base.db_connect_timeout_seconds},
    )
    try:
        try:
            with admin_engine.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        except OperationalError as exc:
            pytest.fail(
                f"Cannot reach PostgreSQL at {base.postgres_host}:{base.postgres_port} "
                f"as '{base.postgres_user}': {exc.orig}\n"
                "Start it first (see README), or run only DB-free tests with: pytest -m 'not db'",
                pytrace=False,
            )

        settings = base.model_copy(update={"postgres_db": name})
        try:
            if migrate:
                upgrade(settings)
            yield settings
        finally:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin_engine.dispose()
