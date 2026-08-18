from __future__ import annotations

import json
from pathlib import Path

from scripts.phase_01.validate_physical_gate_evidence import validate

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "infrastructure/home_server/evidence/venom_physical_gate.json"


def load_evidence() -> dict[str, object]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_current_physical_evidence_is_sanitized_and_in_progress() -> None:
    payload = load_evidence()

    assert validate(payload) == []
    assert payload["acceptance"]["phase_5b"] == "NOT_STARTED"
    assert payload["acceptance"]["stability_24h"] == "WAITING"
    assert payload["acceptance"]["stability_7d"] == "WAITING"


def test_current_evidence_rejects_a_claimed_stability_pass() -> None:
    payload = load_evidence()
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["stability_24h"] = "PASS"

    assert "stability or phase boundary status is invalid" in validate(payload)


def test_current_evidence_rejects_stale_private_lan_address() -> None:
    payload = load_evidence()
    network = payload["network"]
    assert isinstance(network, dict)
    network["ethernet_ipv4"] = "192.168.1.21/24"

    assert "current non-RFC1918 Ethernet evidence is missing" in validate(payload)
