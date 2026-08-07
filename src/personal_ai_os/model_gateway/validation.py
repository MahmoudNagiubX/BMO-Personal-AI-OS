"""Deterministic bounded validation for requests and structured values."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from personal_ai_os.model_gateway.errors import GatewayErrorCategory, ModelGatewayError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCHEMA_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "maxLength",
    "minLength",
    "enum",
}


def require_identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ModelGatewayError(
            GatewayErrorCategory.INVALID_REQUEST,
            f"invalid_{name}",
            f"{name} must be a bounded safe identifier",
        )
    return value


def require_tool_name(value: object) -> str:
    if not isinstance(value, str) or not _TOOL_NAME.fullmatch(value):
        raise ModelGatewayError(
            GatewayErrorCategory.INVALID_REQUEST,
            "invalid_tool_name",
            "tool names must be bounded lowercase snake_case identifiers",
        )
    return value


def validate_schema(schema: object, *, depth: int = 0) -> Mapping[str, Any]:
    """Validate the small JSON-schema subset accepted by the gateway."""

    if depth > 8 or not isinstance(schema, Mapping):
        _invalid_schema()
    assert isinstance(schema, Mapping)
    if set(schema) - _SCHEMA_KEYS:
        _invalid_schema()
    schema_type = schema.get("type")
    if schema_type not in _SCHEMA_TYPES:
        _invalid_schema()
    enum_values = schema.get("enum")
    if enum_values is not None and (
        not isinstance(enum_values, Sequence)
        or isinstance(enum_values, (str, bytes))
        or not enum_values
        or len(enum_values) > 64
    ):
        _invalid_schema()

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", False)
        if (
            not isinstance(properties, Mapping)
            or len(properties) > 64
            or not isinstance(required, list)
            or any(not isinstance(item, str) or item not in properties for item in required)
            or additional is not False
        ):
            _invalid_schema()
        for child in properties.values():
            validate_schema(child, depth=depth + 1)
    elif schema_type == "array":
        if "items" not in schema:
            _invalid_schema()
        validate_schema(schema["items"], depth=depth + 1)
    elif "properties" in schema or "required" in schema or "items" in schema:
        _invalid_schema()

    for key in ("maxLength", "minLength"):
        bound = schema.get(key)
        if bound is not None and (
            not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
        ):
            _invalid_schema()
    return schema


def validate_structured_value(value: Any, schema: Mapping[str, Any], *, depth: int = 0) -> None:
    """Fail closed when a value does not satisfy the accepted schema subset."""

    if depth > 8:
        _invalid_structured()
    expected = schema["type"]
    valid_type = {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[expected]
    if not valid_type:
        _invalid_structured()
    if "enum" in schema and value not in schema["enum"]:
        _invalid_structured()
    if expected == "object":
        assert isinstance(value, Mapping)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if set(required) - set(value) or set(value) - set(properties):
            _invalid_structured()
        for key, child in value.items():
            validate_structured_value(child, properties[key], depth=depth + 1)
    elif expected == "array":
        assert isinstance(value, list)
        for child in value:
            validate_structured_value(child, schema["items"], depth=depth + 1)
    elif expected == "string":
        assert isinstance(value, str)
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if (minimum is not None and len(value) < minimum) or (
            maximum is not None and len(value) > maximum
        ):
            _invalid_structured()


def _invalid_schema() -> None:
    raise ModelGatewayError(
        GatewayErrorCategory.INVALID_REQUEST,
        "invalid_schema",
        "the structured-output schema is outside the bounded supported subset",
    )


def _invalid_structured() -> None:
    raise ModelGatewayError(
        GatewayErrorCategory.STRUCTURED_OUTPUT_INVALID,
        "structured_output_invalid",
        "the provider output did not satisfy the requested schema",
    )


__all__ = [
    "require_identifier",
    "require_tool_name",
    "validate_schema",
    "validate_structured_value",
]
