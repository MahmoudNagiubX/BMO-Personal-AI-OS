from __future__ import annotations

import json
import logging

from personal_ai_os.core.correlation import correlation_id_context
from personal_ai_os.core.logging import JsonFormatter


def test_json_formatter_has_expected_fields_and_redacts_sensitive_message_values() -> None:
    token = correlation_id_context.set("logging-test")
    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=(
                "database_url=postgresql://bmo:super-secret@127.0.0.1/bmo "
                "authorization=secret-token"
            ),
            args=(),
            exc_info=None,
        )
        record.method = "GET"
        record.path = "/health/live"
        record.status_code = 200
        record.duration_ms = 1.2

        payload = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id_context.reset(token)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["correlation_id"] == "logging-test"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert "super-secret" not in payload["message"]
    assert "secret-token" not in payload["message"]
    assert "authorization" in payload["message"]
