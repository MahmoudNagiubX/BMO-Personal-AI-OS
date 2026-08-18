"""Validate a sanitized, owner-provided VENOM foundation handoff."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "phase-01-lenovo-foundation/v1"
EXPECTED_STRINGS = {
    ("identity", "runtime_name"): "VENOM",
    ("identity", "hostname"): "venom-server",
    ("identity", "linux_user"): "venom",
    ("identity", "operating_system"): "Ubuntu Server 24.04.4 LTS",
    ("identity", "architecture"): "x86_64",
    ("hardware", "machine"): "Lenovo G450",
    ("hardware", "cpu_model"): "Intel Core 2 Duo T6500",
    ("storage", "system_disk"): "/dev/sda",
    ("storage", "model"): "ST9320325AS",
    ("storage", "smart_health"): "clean",
    ("storage", "smart_short_test"): "passed",
    ("connectivity", "ssh_test_command"): "ssh venom@192.168.1.21",
    ("proof_of_life", "workspace"): "~/venom",
    ("proof_of_life", "endpoint_result"): "VENOM online / brain initialized",
}
EXPECTED_INTEGERS = {
    ("hardware", "cpu_cores"): 2,
    ("hardware", "ram_gib_approx"): 4,
    ("storage", "capacity_gib_approx"): 298,
    ("storage", "reallocated_sectors"): 0,
    ("storage", "pending_sectors"): 0,
    ("storage", "offline_uncorrectable_sectors"): 0,
}
EXPECTED_BOOLEANS = {
    ("connectivity", "ssh_enabled"): True,
    ("connectivity", "ssh_reachable"): True,
    ("connectivity", "ufw_enabled"): True,
    ("connectivity", "ssh_allowed"): True,
    ("proof_of_life", "python_venv_present"): True,
    ("proof_of_life", "fastapi_uvicorn_proof_present"): True,
    ("storage", "smart_supported"): True,
}
REQUIRED_PENDING_GATES = frozenset(
    {
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
    }
)
SENSITIVE_KEY_PARTS = (
    "credential",
    "cookie",
    "mac_address",
    "password",
    "private_key",
    "secret",
    "serial_number",
    "token",
)


def _mapping_at(payload: Mapping[str, Any], path: Sequence[str]) -> Mapping[str, Any] | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def _value_at(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _walk_keys(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if isinstance(value, Mapping):
        keys: list[tuple[str, ...]] = []
        for key, child in value.items():
            key_path = (*prefix, str(key))
            keys.append(key_path)
            keys.extend(_walk_keys(child, key_path))
        return keys
    if isinstance(value, list):
        keys = []
        for child in value:
            keys.extend(_walk_keys(child, prefix))
        return keys
    return []


def validate_payload(payload: object) -> list[str]:
    """Return validation errors without echoing evidence values."""

    if not isinstance(payload, Mapping):
        return ["top-level evidence must be an object"]

    errors: list[str] = []
    for key_path in _walk_keys(payload):
        if any(part.casefold() in SENSITIVE_KEY_PARTS for part in key_path):
            errors.append("evidence contains a prohibited sensitive field name")
            break

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if payload.get("evidence_source") != "owner-provided VENOM_SERVER_FOUNDATION_COMPLETE_HANDOFF":
        errors.append("evidence_source must identify the owner-provided handoff")

    for path, expected_string in EXPECTED_STRINGS.items():
        if _value_at(payload, path) != expected_string:
            errors.append(f"verified string field missing or mismatched: {'.'.join(path)}")
    for path, expected_integer in EXPECTED_INTEGERS.items():
        if _value_at(payload, path) != expected_integer:
            errors.append(f"verified numeric field missing or mismatched: {'.'.join(path)}")
    for path, expected_boolean in EXPECTED_BOOLEANS.items():
        if _value_at(payload, path) is not expected_boolean:
            errors.append(f"verified boolean field missing or mismatched: {'.'.join(path)}")

    gate = _mapping_at(payload, ("physical_gate",))
    if gate is None or gate.get("status") != "incomplete":
        errors.append("physical_gate.status must remain incomplete")
    pending = gate.get("pending", []) if gate is not None else []
    if not isinstance(pending, list) or not REQUIRED_PENDING_GATES.issubset(
        {item for item in pending if isinstance(item, str)}
    ):
        errors.append("physical_gate.pending must retain every remaining safety gate")

    return errors


def load_payload(path: Path) -> object:
    """Load JSON from a caller-selected local path."""

    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="sanitized evidence JSON")
    args = parser.parse_args()
    try:
        payload = load_payload(args.input)
        errors = validate_payload(payload)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"Evidence validation could not read the input: {type(exc).__name__}", file=sys.stderr
        )
        return 2
    if errors:
        print("Foundation evidence validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Sanitized VENOM foundation handoff accepted; physical safety gate remains incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
