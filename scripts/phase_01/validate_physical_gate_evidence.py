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
    if payload.get("evidence_status") not in {
        "IN PROGRESS",
        "PASS WITH FOLLOWUPS",
        "WAITING_FOR_24H",
        "WAITING_FOR_7D",
        "BLOCKED",
        "PASS",
    }:
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
    if (
        not isinstance(acceptance, Mapping)
        or acceptance.get("stability_24h") != "WAITING"
        or acceptance.get("stability_7d") != "WAITING"
        or acceptance.get("phase_5b") != "NOT_STARTED"
    ):
        errors.append("stability or phase boundary status is invalid")
    if not isinstance(monitor, Mapping) or monitor.get("gate_start_timestamp_utc") is None:
        errors.append("monitor start marker is missing")
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
