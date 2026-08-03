"""The only module allowed to import OpenJarvis directly."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from typing import Any

from openjarvis.core.types import Message, Role  # type: ignore[import-untyped]
from openjarvis.engine.openai_compat_engines import VLLMEngine  # type: ignore[import-untyped]
from openjarvis.tools._stubs import ToolSpec  # type: ignore[import-untyped]

from bmo_openjarvis_adapter.contracts import ToolDefinition
from bmo_openjarvis_adapter.errors import (
    AdapterErrorCategory,
    OpenJarvisAdapterError,
)

UPSTREAM_PACKAGE = "openjarvis"
UPSTREAM_VERSION = "1.0.0"
UPSTREAM_COMMIT = "e97088f199cf86ea5f78de921772357d1f0d2cec"
UPSTREAM_REPOSITORY = "https://github.com/open-jarvis/OpenJarvis"


def identity() -> dict[str, str]:
    """Return the build-time pinned identity and verify installed metadata."""
    try:
        installed_version = importlib.metadata.version(UPSTREAM_PACKAGE)
    except importlib.metadata.PackageNotFoundError as exc:
        raise OpenJarvisAdapterError(
            AdapterErrorCategory.UPSTREAM_COMPATIBILITY,
            "the pinned OpenJarvis distribution is not installed",
        ) from exc
    if installed_version != UPSTREAM_VERSION:
        raise OpenJarvisAdapterError(
            AdapterErrorCategory.UPSTREAM_COMPATIBILITY,
            "the installed OpenJarvis version does not match the approved spike",
        )
    return {
        "package": UPSTREAM_PACKAGE,
        "version": installed_version,
        "commit": UPSTREAM_COMMIT,
        "repository": UPSTREAM_REPOSITORY,
    }


def generate(
    provider_url: str,
    prompt: str,
    *,
    model_id: str,
    temperature: float,
    max_tokens: int,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Execute one request through OpenJarvis's real local engine implementation."""
    engine = VLLMEngine(host=provider_url, timeout=timeout_seconds)
    try:
        messages = [Message(role=Role.USER, content=prompt)]
        result = engine.generate(
            messages,
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not isinstance(result, Mapping):
            raise OpenJarvisAdapterError(
                AdapterErrorCategory.UPSTREAM_COMPATIBILITY,
                "OpenJarvis returned an unsupported response shape",
            )
        return result
    finally:
        engine.close()


def translate_tool(tool: ToolDefinition) -> Mapping[str, Any]:
    """Construct the real upstream declarative schema and return JSON-safe data."""
    upstream_spec = ToolSpec(
        name=tool.name,
        description=tool.description,
        parameters=dict(tool.input_schema),
    )
    return {
        "name": upstream_spec.name,
        "description": upstream_spec.description,
        "parameters": dict(upstream_spec.parameters),
    }


__all__ = [
    "UPSTREAM_COMMIT",
    "UPSTREAM_PACKAGE",
    "UPSTREAM_REPOSITORY",
    "UPSTREAM_VERSION",
    "generate",
    "identity",
    "translate_tool",
]
