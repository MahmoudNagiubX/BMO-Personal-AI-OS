"""Unit coverage for product-owned OpenJarvis contracts."""

from __future__ import annotations

import pytest
from bmo_openjarvis_adapter import LocalModelRequest, OpenJarvisAdapter, ToolDefinition
from bmo_openjarvis_adapter.errors import AdapterErrorCategory, OpenJarvisAdapterError


def _request(
    *, request_id: str = "phase3-request", model_id: str = "synthetic-local-model"
) -> LocalModelRequest:
    return LocalModelRequest(
        request_id=request_id,
        model_id=model_id,
        prompt="synthetic prompt",
    )


@pytest.mark.parametrize("request_id", ["phase3-request", "phase3.request_01"])
def test_request_identifiers_accept_bounded_safe_values(request_id: str) -> None:
    assert _request(request_id=request_id).request_id == request_id


@pytest.mark.parametrize(
    "request_id",
    ["phase3 request", "phase3/request", "phase3\nrequest", "Bearer synthetic-secret"],
)
def test_request_identifiers_reject_unsafe_values(request_id: str) -> None:
    with pytest.raises(ValueError, match="request_id"):
        _request(request_id=request_id)


@pytest.mark.parametrize(
    "model_id",
    ["synthetic-local-model", "qwen3.5:4b", "local/qwen3.5:9b"],
)
def test_model_identifiers_accept_namespaced_tags(model_id: str) -> None:
    assert _request(model_id=model_id).model_id == model_id


@pytest.mark.parametrize(
    "model_id", ["model name", "model?token=secret", "model#fragment", r"C:\private\model"]
)
def test_model_identifiers_reject_unsafe_values(model_id: str) -> None:
    with pytest.raises(ValueError, match="model_id"):
        _request(model_id=model_id)


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
