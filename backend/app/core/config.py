"""Environment-based application settings.

Every value comes from environment variables, optionally loaded from a ``.env`` file at the
repository root. There are deliberately no default credentials: database name, user and password
must be provided, so a misconfigured deployment fails at startup instead of silently connecting
with a well-known password.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# <repo>/backend/app/core/config.py -> <repo>/.env  (silently ignored if the file does not exist,
# e.g. inside the Docker image, where configuration arrives as real environment variables).
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",  # .env may contain variables that only docker-compose cares about
    )

    environment: Literal["development", "test", "production"] = "development"

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr

    db_connect_timeout_seconds: int = Field(default=5, ge=1)

    @field_validator("postgres_password")
    @classmethod
    def _password_must_not_be_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("must not be empty")
        return value

    @property
    def sqlalchemy_url(self) -> URL:
        """SQLAlchemy URL for the psycopg (v3) driver.

        Built with ``URL.create`` rather than string formatting so passwords containing
        characters such as ``@``, ``:`` or ``/`` are escaped correctly.
        """
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings. Used as the default by ``create_app`` and by Alembic."""
    return Settings()
