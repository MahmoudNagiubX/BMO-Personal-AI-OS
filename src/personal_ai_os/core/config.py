"""Validated environment-backed application settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
DEFAULT_DATABASE_URL = "postgresql+psycopg://bmo:bmo_dev_only@127.0.0.1:5432/bmo"


class Settings(BaseSettings):
    """Configuration required by the Phase 2 API and database foundation."""

    model_config = SettingsConfigDict(
        env_prefix="BMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="BMO Personal AI OS", min_length=1, max_length=200)
    environment: Environment = "development"
    database_url: str = DEFAULT_DATABASE_URL
    log_level: LogLevel = "INFO"
    build_sha: str = Field(default="unknown", min_length=1, max_length=128)
    docs_enabled: bool = True
    readiness_timeout_seconds: float = Field(default=1.0, gt=0, le=5)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Require a PostgreSQL URL with a database name."""

        parsed = urlsplit(value)
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("database_url must use a PostgreSQL URL scheme")
        if not parsed.hostname or parsed.path in {"", "/"}:
            raise ValueError("database_url must include a host and database name")
        return value

    @field_validator("build_sha")
    @classmethod
    def validate_build_sha(cls, value: str) -> str:
        """Allow only safe build identifiers in the public version response."""

        if not all(character.isalnum() or character in ".-_" for character in value):
            raise ValueError("build_sha contains unsupported characters")
        return value

    @model_validator(mode="after")
    def reject_development_database_in_production(self) -> Settings:
        """Prevent production from silently using the local development URL."""

        if self.environment == "production" and "dev_only" in self.database_url.casefold():
            raise ValueError("production requires a non-development database_url")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings; tests can call ``cache_clear`` to reset them."""

    return Settings()
