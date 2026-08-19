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
    assert payload["acceptance"]["physical_safety_gate"] == "WAITING_FOR_24H"
    authorization = payload["progression_authorization"]
    assert isinstance(authorization, dict)
    assert authorization["status"] == "OWNER_WAIVER"
    assert authorization["phase_1_progression"] == "ACCEPTED_WITH_OWNER_WAIVER"
    assert authorization["phase_5b"] == "AUTHORIZED_TO_START / NOT_YET_IMPLEMENTED"


def test_legitimate_waiting_for_7d_state_validates() -> None:
    payload = load_evidence()
    payload["evidence_status"] = "WAITING_FOR_7D"
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["physical_safety_gate"] = "WAITING_FOR_7D"
    acceptance["stability_24h"] = "PASS"

    assert validate(payload) == []


def test_legitimate_future_pass_state_validates() -> None:
    payload = load_evidence()
    payload["evidence_status"] = "PASS"
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["physical_safety_gate"] = "PASS"
    acceptance["stability_24h"] = "PASS"
    acceptance["stability_7d"] = "PASS"

    assert validate(payload) == []


def test_current_evidence_rejects_a_claimed_stability_pass() -> None:
    payload = load_evidence()
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["stability_24h"] = "PASS"

    assert "WAITING_FOR_24H state is contradictory" in validate(payload)


def test_owner_waiver_does_not_make_a_waiting_stability_gate_pass() -> None:
    payload = load_evidence()
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["stability_24h"] = "PASS"
    acceptance["stability_7d"] = "PASS"
    authorization = payload["progression_authorization"]
    assert isinstance(authorization, dict)
    assert authorization["status"] == "OWNER_WAIVER"

    assert "WAITING_FOR_24H state is contradictory" in validate(payload)


def test_validator_rejects_claimed_phase_pass_while_stability_waits() -> None:
    payload = load_evidence()
    payload["evidence_status"] = "PASS"

    errors = validate(payload)

    assert "PASS state is contradictory or stability is incomplete" in errors


def test_validator_rejects_claimed_phase_pass_without_durable_monitor() -> None:
    payload = load_evidence()
    payload["evidence_status"] = "PASS"
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    for field in ("thermal", "memory", "ssh_key", "stability_24h", "stability_7d"):
        acceptance[field] = "PASS"
    monitor = payload["stability_monitor"]
    assert isinstance(monitor, dict)
    monitor["system_timer"] = "inactive"
    monitor["durable_monitoring"] = False

    assert "durable privileged stability monitoring prerequisite is incomplete" in validate(payload)


def test_validator_rejects_claimed_phase_pass_without_backup_restore() -> None:
    payload = load_evidence()
    payload["evidence_status"] = "PASS"
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    for field in ("thermal", "memory", "ssh_key", "stability_24h", "stability_7d"):
        acceptance[field] = "PASS"
    monitor = payload["stability_monitor"]
    assert isinstance(monitor, dict)
    monitor["system_timer"] = "active"
    monitor["durable_monitoring"] = True
    backup_restore = payload["backup_restore"]
    assert isinstance(backup_restore, dict)
    backup_restore["status"] = "INCOMPLETE"
    backup_restore["restore_proof"] = "NOT_RUN"

    assert "encrypted backup and restore prerequisites are incomplete" in validate(payload)


def test_validator_rejects_claimed_phase_pass_without_reboot_recovery() -> None:
    payload = load_evidence()
    payload["evidence_status"] = "PASS"
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    for field in ("thermal", "memory", "ssh_key", "stability_24h", "stability_7d"):
        acceptance[field] = "PASS"
    monitor = payload["stability_monitor"]
    assert isinstance(monitor, dict)
    monitor["system_timer"] = "active"
    monitor["durable_monitoring"] = True
    backup_restore = payload["backup_restore"]
    assert isinstance(backup_restore, dict)
    backup_restore["status"] = "PASS"
    backup_restore["restore_proof"] = "PASS"
    reboot_recovery = payload["reboot_recovery"]
    assert isinstance(reboot_recovery, dict)
    reboot_recovery["status"] = "NOT_PERFORMED"
    reboot_recovery["recovery_verified"] = False

    assert "controlled reboot recovery prerequisite is incomplete" in validate(payload)


def test_current_evidence_rejects_stale_private_lan_address() -> None:
    payload = load_evidence()
    network = payload["network"]
    assert isinstance(network, dict)
    network["ethernet_ipv4"] = "192.168.1.21/24"

    assert "current non-RFC1918 Ethernet evidence is missing" in validate(payload)


def test_validator_rejects_unsanitized_persistent_backup_path() -> None:
    payload = load_evidence()
    backup_restore = payload["backup_restore"]
    assert isinstance(backup_restore, dict)
    backup_restore["persistent_copy_path"] = "C:\\Users\\owner\\VENOM-Backups\\Phase-01"

    assert "persistent backup representation is not sanitized" in validate(payload)
