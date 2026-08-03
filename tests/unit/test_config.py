from __future__ import annotations

import pytest
from pydantic import ValidationError

from personal_ai_os.core.config import DEFAULT_DATABASE_URL, Settings, get_settings


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://bmo:bmo_dev_only@127.0.0.1:5432/bmo",
        "postgres://bmo:bmo_dev_only@127.0.0.1:5432/bmo",
        "sqlite:///not-allowed.db",
    ],
)
def test_non_psycopg_database_schemes_are_rejected(database_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=database_url)


def test_psycopg_database_scheme_is_accepted() -> None:
    settings = Settings(database_url="postgresql+psycopg://bmo:bmo_dev_only@127.0.0.1:5432/bmo")

    assert settings.database_url.startswith("postgresql+psycopg://")


def test_production_rejects_development_database_url() -> None:
    with pytest.raises(ValidationError, match="non-development"):
        Settings(environment="production", database_url=DEFAULT_DATABASE_URL)


def test_settings_cache_can_be_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMO_BUILD_SHA", "test-sha")
    get_settings.cache_clear()

    assert get_settings().build_sha == "test-sha"

    monkeypatch.setenv("BMO_BUILD_SHA", "other-sha")
    assert get_settings().build_sha == "test-sha"
    get_settings.cache_clear()
    assert get_settings().build_sha == "other-sha"
    get_settings.cache_clear()
