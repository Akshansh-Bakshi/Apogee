"""Migrations: a fresh database is fully initialised, is reversible, and matches the models."""

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

import app.models  # noqa: F401  (registers models on Base.metadata)
from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_db_engine
from tests.db_utils import ALEMBIC_INI, downgrade, temporary_database, upgrade

pytestmark = pytest.mark.db

APP_TABLES = {
    "users",
    "devices",
    "pages",
    "browsing_events",
    "page_chunks",
    "page_chunk_embeddings",
}

EXPECTED_INDEXES = {
    "devices": {"ix_devices_user_id", "uq_devices_id_user_id"},
    "pages": {
        "uq_pages_user_id_canonical_url",
        "uq_pages_id_user_id",
        "ix_pages_user_id_domain",
        "ix_pages_user_id_last_seen_at",
    },
    "browsing_events": {
        "ix_browsing_events_user_id_occurred_at",
        "ix_browsing_events_device_id_occurred_at",
        "ix_browsing_events_user_id_domain_occurred_at",
        "ix_browsing_events_page_id",
        "ix_browsing_events_user_id_session_id",
    },
    "page_chunk_embeddings": {
        "ix_page_chunk_embeddings_user_id",
        "ix_page_chunk_embeddings_embedding_hnsw",
    },
}


def existing_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_fresh_database_is_initialised_by_migrations(engine: Engine) -> None:
    assert APP_TABLES <= existing_tables(engine)

    with engine.connect() as connection:
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
    migration_head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    assert version == migration_head


def test_migration_enables_the_pgvector_extension(engine: Engine) -> None:
    with engine.connect() as connection:
        version = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))

    assert version


@pytest.mark.parametrize("table", sorted(EXPECTED_INDEXES))
def test_indexes_for_the_planned_queries_exist(engine: Engine, table: str) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"),
            {"t": table},
        )
        actual = {row.indexname for row in rows}

    assert EXPECTED_INDEXES[table] <= actual


def test_models_and_migrations_have_not_drifted(engine: Engine) -> None:
    def ignore_version_table(obj: object, name: str | None, type_: str, *_: object) -> bool:
        return not (type_ == "table" and name == "alembic_version")

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "include_object": ignore_version_table},
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], f"models differ from the migrated schema: {differences}"


def test_embedding_hnsw_index_uses_cosine_distance(engine: Engine) -> None:
    with engine.connect() as connection:
        indexdef = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "AND indexname = 'ix_page_chunk_embeddings_embedding_hnsw'"
            )
        )

    assert indexdef is not None
    assert "USING hnsw (embedding vector_cosine_ops)" in indexdef


def test_migration_can_be_downgraded_and_reapplied(base_settings: Settings) -> None:
    with temporary_database(base_settings, migrate=True) as settings:
        downgrade(settings, "base")
        db_engine = create_db_engine(settings)
        try:
            assert not (APP_TABLES & existing_tables(db_engine))

            upgrade(settings, "head")

            assert APP_TABLES <= existing_tables(db_engine)
        finally:
            db_engine.dispose()
