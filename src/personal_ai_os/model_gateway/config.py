"""Safe, bounded model gateway configuration."""

from __future__ import annotations

from ipaddress import ip_address
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Validated software-only gateway settings with local-only defaults."""

    model_config = SettingsConfigDict(
        env_prefix="BMO_MODEL_GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = True
    ollama_endpoint: str = "http://127.0.0.1:11434"
    llama_cpp_endpoint: str = "http://127.0.0.1:11435"
    llama_cpp_model_path: str = str(
        Path.home()
        / "BMO"
        / "phase-08-5-models"
        / "Qwen3.5-9B-ultra-uncensored-heretic-v2-Q4_K_M.gguf"
    )
    llama_cpp_model_sha256: str = "8d463c63e2c8759ad263cba59f1fa7a0be9a7cacb59b0fd0a787b7daa31597ad"
    expected_llama_cpp_build: str = "b10502-0adcc3bb5"
    llama_cpp_enabled: bool = True
    llama_cpp_generation_timeout_seconds: float = Field(default=180.0, gt=0, le=300)
    llama_cpp_sleep_idle_seconds: int = Field(default=12, ge=1, le=300)
    allow_private_network_endpoint: bool = False
    expected_ollama_version: str = "0.32.5"
    health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    generation_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_attempts: int = Field(default=2, ge=1, le=2)
    retry_backoff_seconds: float = Field(default=0.05, ge=0, le=1)
    circuit_failure_threshold: int = Field(default=2, ge=1, le=10)
    circuit_cooldown_seconds: float = Field(default=30.0, gt=0, le=300)
    concurrency_limit: int = Field(default=1, ge=1, le=1)
    concurrency_wait_seconds: float = Field(default=0.1, ge=0, le=5)
    max_messages: int = Field(default=32, ge=1, le=64)
    max_total_text_chars: int = Field(default=65_536, ge=1, le=131_072)
    max_image_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=10 * 1024 * 1024)
    max_images: int = Field(default=4, ge=1, le=8)
    max_embedding_batch_size: int = Field(default=16, ge=1, le=64)
    max_embedding_text_chars: int = Field(default=8_192, ge=1, le=32_768)
    max_embedding_total_chars: int = Field(default=32_768, ge=1, le=131_072)

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
        self.ollama_endpoint = validate_ollama_endpoint(
            self.ollama_endpoint,
            allow_private_network=self.allow_private_network_endpoint,
        )
        self.llama_cpp_endpoint = validate_local_endpoint(self.llama_cpp_endpoint)
        if self.llama_cpp_enabled and not self.llama_cpp_model_path.strip():
            raise ValueError(
                "llama_cpp_model_path is required when the advanced provider is enabled"
            )
        return self


def validate_ollama_endpoint(value: str, *, allow_private_network: bool = False) -> str:
    """Allow loopback, or an explicitly enabled private IP for a later phase."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("ollama_endpoint is not a valid local HTTP endpoint") from exc

    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ollama_endpoint must be an unauthenticated local HTTP origin")
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ValueError("ollama_endpoint must use an IP literal, not a hostname") from exc
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ValueError("ollama_endpoint uses a forbidden address class")
    if not address.is_loopback and not (allow_private_network and address.is_private):
        raise ValueError("ollama_endpoint must be loopback unless private deployment is explicit")
    normalized_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{normalized_host}:{port}"


def validate_local_endpoint(value: str) -> str:
    """Validate the loopback-only llama.cpp HTTP endpoint."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("llama_cpp_endpoint is not a valid local HTTP endpoint") from exc
    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("llama_cpp_endpoint must be a loopback HTTP origin")
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ValueError("llama_cpp_endpoint must use a loopback IP literal") from exc
    if not address.is_loopback:
        raise ValueError("llama_cpp_endpoint must remain loopback-only")
    normalized_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{normalized_host}:{port}"


__all__ = ["GatewaySettings", "validate_local_endpoint", "validate_ollama_endpoint"]
