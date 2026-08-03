"""Small standard-library JSON logging configuration."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from personal_ai_os.core.correlation import get_correlation_id

_BMO_HANDLER = "_bmo_json_handler"
_SENSITIVE_MESSAGE = re.compile(
    r"(?i)(password|token|authorization|cookie|database_url)\s*[:=]\s*[^\s,;]+"
)
_EXTRA_FIELDS = ("method", "path", "status_code", "duration_ms")


class JsonFormatter(logging.Formatter):
    """Format a deliberately limited set of safe structured log fields."""

    def format(self, record: logging.LogRecord) -> str:
        message = _SENSITIVE_MESSAGE.sub(r"\1=[REDACTED]", record.getMessage())
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        correlation_id = get_correlation_id()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(level: str) -> None:
    """Install one JSON stream handler without duplicating it on app creation."""

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        if getattr(handler, _BMO_HANDLER, False):
            handler.setLevel(level)
            return

    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _BMO_HANDLER, True)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
