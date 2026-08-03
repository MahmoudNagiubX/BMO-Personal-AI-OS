"""Sanitized translation of OpenJarvis inference event data."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """Product-owned, non-persistent trace event with bounded metadata."""

    trace_id: str
    event_type: str
    timestamp: float
    message: str
    metadata: Mapping[str, str | int | float | bool]
    source_framework: str
    redacted: bool


_SAFE_KEYS = {
    "request_id",
    "model_id",
    "finish_reason",
    "provider",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "local_provider",
}
_USAGE_KEYS = {"prompt_tokens", "completion_tokens", "total_tokens"}
_SECRET_VALUE = re.compile(r"(?:bearer|basic)\s+\S+|(?:postgres|mysql|sqlite)://\S+", re.I)
_MAX_METADATA = 16
_MAX_STRING = 128


def translate_trace(source: Mapping[str, Any], *, trace_id: str) -> TraceEvent:
    """Keep only known scalar fields and mark anything removed as redacted."""
    metadata: dict[str, str | int | float | bool] = {}
    redacted = False
    for raw_key, raw_value in source.items():
        key = raw_key.lower().replace("-", "_") if isinstance(raw_key, str) else ""
        if key in {"usage", "telemetry"}:
            if isinstance(raw_value, Mapping):
                for usage_key, usage_value in raw_value.items():
                    if usage_key in _USAGE_KEYS and _safe_scalar(usage_value):
                        metadata[usage_key] = usage_value
                    else:
                        redacted = True
            else:
                redacted = True
            continue
        if key not in _SAFE_KEYS or len(metadata) >= _MAX_METADATA:
            redacted = True
            continue
        if _safe_scalar(raw_value):
            metadata[key] = raw_value
        else:
            redacted = True
    timestamp = source.get("timestamp")
    safe_timestamp = timestamp if isinstance(timestamp, (int, float)) else time.time()
    if not math.isfinite(float(safe_timestamp)) or float(safe_timestamp) <= 0:
        safe_timestamp = time.time()
        redacted = True
    return TraceEvent(
        trace_id=trace_id,
        event_type="model_response",
        timestamp=float(safe_timestamp),
        message="OpenJarvis local model response translated",
        metadata=metadata,
        source_framework="openjarvis",
        redacted=redacted,
    )


def _safe_scalar(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return 0 <= value <= 1_000_000_000
    if isinstance(value, float):
        return math.isfinite(value) and 0 <= value <= 1_000_000_000
    if isinstance(value, str):
        return len(value) <= _MAX_STRING and not _SECRET_VALUE.search(value)
    return False


__all__ = ["TraceEvent", "translate_trace"]
