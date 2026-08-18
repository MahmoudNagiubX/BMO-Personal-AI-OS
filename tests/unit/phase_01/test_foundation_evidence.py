from __future__ import annotations

import json
from pathlib import Path

from scripts.phase_01.validate_foundation_evidence import validate_payload

ROOT = Path(__file__).resolve().parents[3]
HANDOFF = ROOT / "infrastructure/home_server/evidence/venom_foundation_handoff.json"


def load_handoff() -> dict[str, object]:
    return json.loads(HANDOFF.read_text(encoding="utf-8"))


def test_owner_handoff_is_valid_and_keeps_gate_incomplete() -> None:
    payload = load_handoff()

    assert validate_payload(payload) == []
    assert payload["physical_gate"] == {
        "status": "incomplete",
        "pending": [
            "ethernet",
            "memory",
            "filesystem_lvm_free_space",
            "thermals_fans",
            "battery_power",
            "ssh_hardening",
            "firewall_lan_scope",
            "system_baseline",
            "resource_admission",
            "log_rotation",
            "backup_restore",
            "reboot_recovery",
            "stability_24h",
            "stability_7d",
        ],
    }


def test_validator_rejects_a_claimed_physical_pass() -> None:
    payload = load_handoff()
    physical_gate = payload["physical_gate"]
    assert isinstance(physical_gate, dict)
    physical_gate["status"] = "pass"

    errors = validate_payload(payload)

    assert "physical_gate.status must remain incomplete" in errors


def test_validator_rejects_sensitive_fields() -> None:
    payload = load_handoff()
    payload["credential"] = "synthetic-secret-marker"

    errors = validate_payload(payload)

    assert "evidence contains a prohibited sensitive field name" in errors
