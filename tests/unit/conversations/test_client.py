from __future__ import annotations

import pytest

from scripts.phase_07.text_client import ClientState, parse_event


def test_client_event_parser_requires_strict_replay_order() -> None:
    state = ClientState()
    parsed = parse_event(
        {"sequence": 1, "event_type": "session.ready", "run_id": None, "data": {}}, state
    )
    assert parsed["event_type"] == "session.ready"
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_event(
            {"sequence": 1, "event_type": "session.ready", "run_id": None, "data": {}},
            state,
        )


def test_client_parser_preserves_only_sanitized_event_data() -> None:
    state = ClientState()
    event = parse_event(
        {
            "sequence": 2,
            "event_type": "assistant.message.ready",
            "run_id": "run-1",
            "data": {"assistant_message_id": "message-1", "content": "synthetic"},
        },
        state,
    )
    assert event["run_id"] == "run-1"
    assert event["data"]["content"] == "synthetic"
