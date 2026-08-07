from __future__ import annotations

import pytest

from scripts.phase_04.sanitize_evidence import (
    EvidenceSanitizationError,
    sanitize_document,
    sanitize_restart_evidence,
)


def valid_document() -> dict[str, object]:
    return {
        "phase": "phase-04",
        "schema_version": 1,
        "ollama": {"version": "0.32.5"},
        "models": [],
        "security": {"loopback_only": True},
        "acceptance": "pending",
    }


def test_sanitizer_accepts_bounded_evidence() -> None:
    assert sanitize_document(valid_document())["phase"] == "phase-04"


@pytest.mark.parametrize("restart", [{"status": "pending"}, None])
def test_sanitizer_rejects_accepted_evidence_without_restart(restart: object) -> None:
    document = valid_document()
    document["acceptance"] = "pass"
    document["restart"] = restart
    with pytest.raises(EvidenceSanitizationError):
        sanitize_document(document)


def test_sanitizer_accepts_completed_restart_evidence() -> None:
    document = valid_document()
    document["acceptance"] = "pass"
    document["restart"] = {"status": "pass", "bge_dimension": 1024, "bge_finite": True}
    assert sanitize_document(document)["restart"] == {
        "bge_dimension": 1024,
        "bge_finite": True,
        "status": "pass",
    }


def test_restart_sanitizer_rejects_pending_or_unknown_fields() -> None:
    with pytest.raises(EvidenceSanitizationError):
        sanitize_restart_evidence({"status": "pending"})
    with pytest.raises(EvidenceSanitizationError):
        sanitize_restart_evidence({"status": "pass", "raw_response": "no"})


@pytest.mark.parametrize(
    "bad_value",
    [
        r"C:\Users\owner\secret.txt",
        "https://192.0.2.10/private",
        "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890",
        "AA:BB:CC:DD:EE:FF",
        "SERIALNUMBER=123456",
    ],
)
def test_sanitizer_rejects_adversarial_values(bad_value: str) -> None:
    document = valid_document()
    document["limitations"] = [bad_value]
    with pytest.raises(EvidenceSanitizationError):
        sanitize_document(document)


def test_sanitizer_rejects_sensitive_field_names_and_raw_outputs() -> None:
    document = valid_document()
    document["raw_model_output"] = "do not commit"
    with pytest.raises(EvidenceSanitizationError):
        sanitize_document(document)


def test_sanitizer_allows_literal_loopback_only() -> None:
    document = valid_document()
    document["security"] = {"listener": "127.0.0.1"}
    assert sanitize_document(document)["security"] == {"listener": "127.0.0.1"}


def test_sanitizer_allows_thermal_power_draw_but_rejects_raw_field_segments() -> None:
    document = valid_document()
    document["thermals"] = {"power_draw_w": 42.0}
    assert sanitize_document(document)["thermals"] == {"power_draw_w": 42.0}
    document["thermals"] = {"draw_raw_value": 42.0}
    with pytest.raises(EvidenceSanitizationError):
        sanitize_document(document)
