"""Product-owned request, response, and declarative tool contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from bmo_openjarvis_adapter.trace import TraceEvent, _validate_identifier


@dataclass(frozen=True, slots=True)
class Usage:
    """Bounded usage values returned by a local provider when available."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LocalModelRequest:
    """A deliberately small, product-owned local inference request."""

    request_id: str
    model_id: str
    prompt: str
    temperature: float = 0.0
    max_tokens: int = 128
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier(self.request_id, kind="request_id")
        _validate_identifier(self.model_id, kind="model_id")
        if not self.prompt or len(self.prompt) > 8_192:
            raise ValueError("prompt must be non-empty and at most 8192 characters")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("max_tokens must be between 1 and 4096")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        safe_metadata = {"test_case", "purpose"}
        if any(key not in safe_metadata for key in self.metadata):
            raise ValueError("metadata contains an unsupported key")
        if any(not isinstance(value, str) or len(value) > 128 for value in self.metadata.values()):
            raise ValueError("metadata values must be bounded strings")


@dataclass(frozen=True, slots=True)
class LocalModelResponse:
    """Translated response that does not expose OpenJarvis types."""

    request_id: str
    model_id: str
    text: str
    finish_reason: str
    usage: Usage
    trace_events: tuple[TraceEvent, ...]
    local_provider: bool


_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ALLOWED_SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties"}
_ALLOWED_PROPERTY_KEYS = {"type", "description", "maxLength"}
_ALLOWED_PROPERTY_TYPES = {"string", "boolean"}


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Declarative tool metadata; it contains no executable behavior."""

    name: str
    description: str
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not _TOOL_NAME.fullmatch(self.name):
            raise ValueError("tool name must be lowercase snake_case and at most 64 characters")
        if not self.description or len(self.description) > 512:
            raise ValueError("tool description must be non-empty and at most 512 characters")
        schema = dict(self.input_schema)
        object.__setattr__(self, "input_schema", schema)
        self._validate_schema(schema)

    @staticmethod
    def _validate_schema(schema: Mapping[str, Any]) -> None:
        if set(schema) - _ALLOWED_SCHEMA_KEYS:
            raise ValueError("tool schema contains unsupported top-level keys")
        if schema.get("type") != "object":
            raise ValueError("tool schema type must be object")
        if schema.get("additionalProperties") is not False:
            raise ValueError("tool schema must reject additional properties")
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            raise ValueError("tool schema properties and required must be object/list")
        if any(not isinstance(name, str) for name in properties):
            raise ValueError("tool property names must be strings")
        if any(name not in properties or not isinstance(name, str) for name in required):
            raise ValueError("tool schema required fields must be declared properties")
        for name, property_schema in properties.items():
            if not isinstance(property_schema, Mapping):
                raise ValueError(f"tool property {name!r} must be an object")
            if set(property_schema) - _ALLOWED_PROPERTY_KEYS:
                raise ValueError(f"tool property {name!r} has unsupported keywords")
            if property_schema.get("type") not in _ALLOWED_PROPERTY_TYPES:
                raise ValueError(f"tool property {name!r} must be string or boolean")
            max_length = property_schema.get("maxLength")
            if max_length is not None and (not isinstance(max_length, int) or max_length > 256):
                raise ValueError(f"tool property {name!r} has an invalid maxLength")

    def validate_arguments(self, arguments: Mapping[str, Any]) -> None:
        """Validate arguments without executing or resolving a callable."""
        properties = self.input_schema["properties"]
        required = self.input_schema.get("required", [])
        missing = set(required) - set(arguments)
        extra = set(arguments) - set(properties)
        if missing:
            raise ValueError(f"missing required tool arguments: {sorted(missing)}")
        if extra:
            raise ValueError(f"unsupported tool arguments: {sorted(extra)}")
        for name, value in arguments.items():
            schema = properties[name]
            expected_type = schema["type"]
            if expected_type == "string" and not isinstance(value, str):
                raise ValueError(f"tool argument {name!r} must be a string")
            if expected_type == "boolean" and type(value) is not bool:
                raise ValueError(f"tool argument {name!r} must be a boolean")
            max_length = schema.get("maxLength")
            if max_length is not None and isinstance(value, str) and len(value) > max_length:
                raise ValueError(f"tool argument {name!r} exceeds maxLength")


@dataclass(frozen=True, slots=True)
class OpenJarvisToolSchema:
    """JSON-safe schema produced from the real OpenJarvis ``ToolSpec``."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    source_framework: str = "openjarvis"


__all__ = [
    "LocalModelRequest",
    "LocalModelResponse",
    "OpenJarvisToolSchema",
    "ToolDefinition",
    "Usage",
]
