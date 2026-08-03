"""Stable product-owned errors for the OpenJarvis adapter boundary."""

from __future__ import annotations

from enum import StrEnum


class AdapterErrorCategory(StrEnum):
    """Categories callers can handle without depending on OpenJarvis."""

    CONFIGURATION = "configuration_error"
    UPSTREAM_COMPATIBILITY = "upstream_compatibility_error"
    LOCAL_PROVIDER_UNAVAILABLE = "local_provider_unavailable"
    INVALID_REQUEST = "invalid_request"
    INVALID_TOOL_SCHEMA = "invalid_tool_schema"
    TRACE_TRANSLATION = "trace_translation_failure"


class OpenJarvisAdapterError(RuntimeError):
    """Sanitized adapter failure with a stable product-owned category."""

    def __init__(self, category: AdapterErrorCategory, message: str) -> None:
        self.category = category
        super().__init__(f"{category.value}: {message}")


__all__ = ["AdapterErrorCategory", "OpenJarvisAdapterError"]
