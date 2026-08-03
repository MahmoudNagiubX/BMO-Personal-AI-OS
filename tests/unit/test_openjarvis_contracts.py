"""Unit coverage for product-owned OpenJarvis contracts."""

from __future__ import annotations

import pytest
from bmo_openjarvis_adapter import OpenJarvisAdapter, ToolDefinition
from bmo_openjarvis_adapter.errors import AdapterErrorCategory, OpenJarvisAdapterError


def _demo_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_demo_status",
        description="Return synthetic status for compatibility testing.",
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "A bounded synthetic status scope.",
                    "maxLength": 32,
                },
                "verbose": {"type": "boolean", "description": "Include extra status fields."},
            },
            "required": ["scope"],
            "additionalProperties": False,
        },
    )


def test_tool_schema_translates_without_a_callable() -> None:
    translated = OpenJarvisAdapter("http://127.0.0.1:9").translate_tool(_demo_tool())
    assert translated.name == "get_demo_status"
    assert translated.description.startswith("Return synthetic")
    assert translated.parameters["required"] == ["scope"]
    assert translated.parameters["properties"]["scope"]["maxLength"] == 32
    assert translated.parameters["additionalProperties"] is False
    assert not hasattr(translated, "execute")


def test_tool_arguments_reject_extra_values() -> None:
    with pytest.raises(ValueError, match="unsupported tool arguments"):
        _demo_tool().validate_arguments({"scope": "synthetic", "unexpected": True})


def test_invalid_tool_schema_fails_safely() -> None:
    with pytest.raises(ValueError, match="additional properties"):
        ToolDefinition(
            name="get_demo_status",
            description="Synthetic status.",
            input_schema={
                "type": "object",
                "properties": {"scope": {"type": "array"}},
                "required": [],
                "additionalProperties": True,
            },
        )


def test_upstream_failures_are_product_owned() -> None:
    with pytest.raises(OpenJarvisAdapterError) as exc_info:
        OpenJarvisAdapter("http://127.0.0.1:9", timeout_seconds=0.1).invoke_local_model(
            __import__("bmo_openjarvis_adapter").LocalModelRequest(
                request_id="phase3-error",
                model_id="synthetic-local-model",
                prompt="Return exactly: BMO_OPENJARVIS_SPIKE_OK",
            )
        )
    assert exc_info.value.category is AdapterErrorCategory.LOCAL_PROVIDER_UNAVAILABLE
    assert "httpx" not in str(exc_info.value).lower()
