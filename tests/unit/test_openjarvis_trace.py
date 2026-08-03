"""Unit coverage for bounded OpenJarvis trace translation and redaction."""

from __future__ import annotations

import pytest
from bmo_openjarvis_adapter import translate_trace


def test_trace_translation_preserves_safe_fields() -> None:
    event = translate_trace(
        {
            "request_id": "phase3-trace",
            "model_id": "synthetic-local-model",
            "finish_reason": "stop",
            "provider": "loopback",
            "local_provider": True,
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        },
        trace_id="phase3-trace",
    )
    assert event.trace_id == "phase3-trace"
    assert event.event_type == "model_response"
    assert event.metadata["model_id"] == "synthetic-local-model"
    assert event.metadata["total_tokens"] == 5
    assert event.source_framework == "openjarvis"
    assert event.redacted is False


def test_secret_like_trace_fields_are_redacted() -> None:
    event = translate_trace(
        {
            "request_id": "phase3-redaction",
            "model_id": "synthetic-local-model",
            "authorization": "Bearer synthetic-secret",
            "api_key": "synthetic-api-key",
            "password": "synthetic-password",
            "cookie": "session=synthetic-cookie",
            "database_url": "postgresql://synthetic-user:synthetic-password@localhost/db",
            "absolute_path": "C:\\Users\\Mahmoud\\private\\document.txt",
            "environment_value": "synthetic-env-value",
            "request_body": "Return exactly: private body",
            "stack_locals": {"secret": "synthetic-stack-secret"},
        },
        trace_id="phase3-redaction",
    )
    serialized = repr(event)
    assert event.redacted is True
    assert "synthetic-secret" not in serialized
    assert "synthetic-api-key" not in serialized
    assert "synthetic-password" not in serialized
    assert "private" not in serialized
    assert "synthetic-stack-secret" not in serialized
    assert set(event.metadata) == {"request_id", "model_id"}


def test_unsafe_trace_id_is_rejected_without_echoing_input() -> None:
    unsafe_trace_id = "Bearer synthetic-trace-secret"
    with pytest.raises(ValueError) as exc_info:
        translate_trace({}, trace_id=unsafe_trace_id)
    assert unsafe_trace_id not in str(exc_info.value)


def test_secret_and_path_like_values_are_redacted_under_safe_keys() -> None:
    event = translate_trace(
        {
            "model_id": "api_key=synthetic-key",
            "finish_reason": r"C:\private\model",
            "provider": "Bearer synthetic-token",
        },
        trace_id="phase3-safe-key-redaction",
    )
    assert event.redacted is True
    assert event.metadata == {}


def test_ordinary_safe_values_under_safe_keys_remain() -> None:
    event = translate_trace(
        {
            "model_id": "synthetic-local-model",
            "finish_reason": "stop",
            "provider": "loopback",
        },
        trace_id="phase3-safe-key-values",
    )
    assert event.redacted is False
    assert event.metadata == {
        "model_id": "synthetic-local-model",
        "finish_reason": "stop",
        "provider": "loopback",
    }
