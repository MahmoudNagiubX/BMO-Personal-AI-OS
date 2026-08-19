"""Validate sanitized, current VENOM physical-gate evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {
    "credential",
    "cookie",
    "mac_address",
    "password",
    "private_key",
    "secret",
    "serial_number",
    "token",
}

GATE_STATES = {"WAITING_FOR_24H", "WAITING_FOR_7D", "PASS", "BLOCKED"}


def walk_keys(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [str(key) for key, child in value.items()] + [
            key for child in value.values() for key in walk_keys(child)
        ]
    if isinstance(value, list):
        return [key for child in value for key in walk_keys(child)]
    return []


def validate(payload: object) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["evidence must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != "phase-01-venom-physical-safety-gate/v1":
        errors.append("unsupported physical-gate schema")
    evidence_status = payload.get("evidence_status")
    if evidence_status not in GATE_STATES:
        errors.append("invalid evidence status")
    if any(key.casefold() in SENSITIVE_KEYS for key in walk_keys(payload)):
        errors.append("evidence contains a prohibited sensitive field name")

    server = payload.get("server")
    network = payload.get("network")
    thermal = payload.get("thermal")
    acceptance = payload.get("acceptance")
    monitor = payload.get("stability_monitor")
    if (
        not isinstance(server, Mapping)
        or server.get("hostname") != "venom-server"
        or server.get("operating_system") != "Ubuntu Server 24.04.4 LTS"
    ):
        errors.append("current server identity is not verified")
    if (
        not isinstance(network, Mapping)
        or network.get("ethernet_ipv4") != "192.162.1.21/24"
        or "not RFC1918" not in str(network.get("management_lan_risk"))
    ):
        errors.append("current non-RFC1918 Ethernet evidence is missing")
    if (
        not isinstance(thermal, Mapping)
        or thermal.get("stress_status") != "passed"
        or thermal.get("thermal_stop_triggered") is not False
    ):
        errors.append("bounded thermal acceptance is missing")
    if not isinstance(monitor, Mapping) or monitor.get("gate_start_timestamp_utc") is None:
        errors.append("monitor start marker is missing")

    if not isinstance(acceptance, Mapping):
        errors.append("acceptance state is missing")
        return errors

    progression = payload.get("progression_authorization")
    if (
        not isinstance(progression, Mapping)
        or progression.get("status") != "OWNER_WAIVER"
        or progression.get("date") != "2026-08-19"
        or progression.get("scope") != "Phase 5B progression only"
        or progression.get("phase_1_progression") != "ACCEPTED_WITH_OWNER_WAIVER"
        or progression.get("phase_5b") != "AUTHORIZED_TO_START / NOT_YET_IMPLEMENTED"
    ):
        errors.append("owner-waiver progression authorization is missing or invalid")

    immediate_fields = ("thermal", "memory", "ssh_key")
    if any(acceptance.get(field) != "PASS" for field in immediate_fields):
        errors.append("immediate physical prerequisites are incomplete")
    backup_restore = payload.get("backup_restore")
    if (
        not isinstance(backup_restore, Mapping)
        or backup_restore.get("status") != "PASS"
        or backup_restore.get("restore_proof") != "PASS"
    ):
        errors.append("encrypted backup and restore prerequisites are incomplete")
    elif (
        backup_restore.get("persistent_copy_path")
        != "%USERPROFILE%\\VENOM-Backups\\Phase-01\\venom-phase1-config.tar.gz.gpg"
        or backup_restore.get("checksum_sidecar_path")
        != "%USERPROFILE%\\VENOM-Backups\\Phase-01\\venom-phase1-config.tar.gz.sha256"
    ):
        errors.append("persistent backup representation is not sanitized")
    reboot_recovery = payload.get("reboot_recovery")
    if (
        not isinstance(reboot_recovery, Mapping)
        or reboot_recovery.get("status") != "PASS"
        or reboot_recovery.get("recovery_verified") is not True
    ):
        errors.append("controlled reboot recovery prerequisite is incomplete")
    if (
        not isinstance(monitor, Mapping)
        or monitor.get("system_timer") != "active"
        or monitor.get("durable_monitoring") is not True
    ):
        errors.append("durable privileged stability monitoring prerequisite is incomplete")

    physical_state = acceptance.get("physical_safety_gate")
    state_fields = ("stability_24h", "stability_7d", "phase_5b")
    if evidence_status == "WAITING_FOR_24H":
        if physical_state != "WAITING_FOR_24H" or any(
            acceptance.get(field) != expected
            for field, expected in zip(
                state_fields, ("WAITING", "WAITING", "NOT_STARTED"), strict=True
            )
        ):
            errors.append("WAITING_FOR_24H state is contradictory")
    elif evidence_status == "WAITING_FOR_7D":
        if physical_state != "WAITING_FOR_7D" or any(
            acceptance.get(field) != expected
            for field, expected in zip(
                state_fields, ("PASS", "WAITING", "NOT_STARTED"), strict=True
            )
        ):
            errors.append("WAITING_FOR_7D state is contradictory")
    elif evidence_status == "PASS":
        if physical_state != "PASS" or any(
            acceptance.get(field) != expected
            for field, expected in zip(state_fields, ("PASS", "PASS", "NOT_STARTED"), strict=True)
        ):
            errors.append("PASS state is contradictory or stability is incomplete")
    elif evidence_status == "BLOCKED" and (
        physical_state != "BLOCKED" or acceptance.get("phase_5b") != "NOT_STARTED"
    ):
        errors.append("BLOCKED state is contradictory")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Physical-gate evidence could not be read: {type(exc).__name__}", file=sys.stderr)
        return 2
    errors = validate(payload)
    if errors:
        print("Physical-gate evidence validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "Sanitized current VENOM physical-gate evidence accepted; "
        "real stability gates remain pending."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
