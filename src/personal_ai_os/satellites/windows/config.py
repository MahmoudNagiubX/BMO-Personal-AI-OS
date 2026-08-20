"""Validated local settings for the per-user Windows satellite."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_state_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / "BMO" / "WindowsSatellite"


class WindowsSatelliteSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BMO_SATELLITE_",
        env_file=None,
        extra="ignore",
    )

    endpoint: str
    allowlist_path: Path = Field(default_factory=lambda: default_state_root() / "allowlist.json")
    state_root: Path = Field(default_factory=default_state_root)
    software_version: str = Field(default="0.0.0-phase09", min_length=1, max_length=64)
    reconnect_max_seconds: float = Field(default=30.0, ge=2.0, le=60.0)
    log_max_bytes: int = Field(default=1_048_576, ge=65_536, le=10_485_760)
    log_backup_count: int = Field(default=3, ge=1, le=5)

    @field_validator("endpoint")
    @classmethod
    def secure_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("satellite endpoint cannot contain credentials, query, or fragment")
        if parsed.path != "/api/v1/satellites/windows/connect":
            raise ValueError("satellite endpoint path is invalid")
        if parsed.scheme == "wss" and parsed.hostname:
            return value
        if parsed.scheme == "ws" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return value
        raise ValueError("production satellite endpoint must use wss")


__all__ = ["WindowsSatelliteSettings", "default_state_root"]
