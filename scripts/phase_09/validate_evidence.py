"""Validate sanitized Phase 9 Windows satellite evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/phase_reports/evidence/PHASE_09_WINDOWS_SATELLITE.json"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_KEYS = {
    "authorization",
    "credential",
    "database_url",
    "enrollment_code",
    "password",
    "private_key",
    "raw_file_results",
    "secret",
    "token",
}
EXPECTED_TOOLS = {
    "windows.status.read": ("read", "none"),
    "windows.files.search": ("read", "none"),
    "windows.app.open": ("reversible", "none"),
    "windows.project.open": ("reversible", "none"),
    "windows.media.volume.get": ("read", "none"),
    "windows.media.volume.set": ("reversible", "none"),
    "windows.workflow.start": ("consequential", "exact_owner"),
}
PHYSICAL_TOOL_KEYS = {
    "connection",
    "telemetry",
    "file_search",
    "app_open",
    "project_open",
    "media_get_set_restore",
    "workflow_approval_execution",
    "workflow_cancellation",
    "offline_recovery",
    "idle_cpu_ram",
    "latency_errors_crashes",
}


def _get(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"missing evidence field: {path}")
        current = current[part]
    return current


def _equal(data: Mapping[str, Any], path: str, expected: Any) -> None:
    if _get(data, path) != expected:
        raise ValueError(f"{path} must equal {expected!r}")


def _reject_sensitive(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise ValueError(f"sensitive evidence key: {path}.{key}")
            _reject_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive(child, f"{path}[{index}]")
    elif isinstance(value, str) and (
        "C:\\Users\\" in value or value.startswith("/home/") or "Bearer " in value
    ):
        raise ValueError(f"unsanitized evidence value: {path}")


def validate(data: Mapping[str, Any] | None = None) -> None:
    if data is None:
        data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("evidence root must be an object")
    _reject_sensitive(data)
    _equal(data, "schema_version", "phase-09-windows-satellite/v1")
    _equal(data, "phase", "phase-09")
    _equal(data, "protocol.version", "phase-09-windows-satellite/v1")
    _equal(data, "protocol.connection_direction", "TUF_OUTBOUND_TO_VENOM")
    _equal(data, "protocol.production_transport", "wss")
    _equal(data, "protocol.inbound_tuf_listener_defined", False)
    _equal(data, "protocol.firewall_mutation_defined", False)
    _equal(data, "identity.new_scope", "satellite.connect")
    _equal(data, "identity.reusable_plaintext_persistence", False)
    _equal(data, "identity.revocation_revalidated_per_frame", True)
    tested_commit = _get(data, "tested_implementation_commit")
    if not isinstance(tested_commit, str) or not COMMIT.fullmatch(tested_commit):
        raise ValueError("tested_implementation_commit must be a full commit SHA")
    _equal(data, "ci.implementation_commit", tested_commit)

    tools = _get(data, "tools")
    if not isinstance(tools, list) or len(tools) != len(EXPECTED_TOOLS):
        raise ValueError("tools must contain the exact Phase 9 catalog")
    observed: dict[str, tuple[str, str]] = {}
    for item in tools:
        if not isinstance(item, Mapping) or set(item) != {"name", "risk", "approval"}:
            raise ValueError("tool evidence shape is invalid")
        observed[str(item["name"])] = (str(item["risk"]), str(item["approval"]))
    if observed != EXPECTED_TOOLS:
        raise ValueError("tool policy evidence does not match the locked catalog")

    repository = _get(data, "repository_acceptance")
    if not isinstance(repository, Mapping) or not repository:
        raise ValueError("repository acceptance evidence is missing")
    if any(value != "PASS" for value in repository.values()):
        raise ValueError("every repository acceptance gate must pass")

    for path, expected in {
        "physical_prerequisite.inspection_mode": "READ_ONLY",
        "physical_prerequisite.phase5b_release_present": True,
        "physical_prerequisite.phase6_deployment_present": False,
        "physical_prerequisite.phase7_deployment_present": False,
        "physical_prerequisite.phase8_deployment_present": False,
        "physical_prerequisite.postgresql_active": False,
        "physical_prerequisite.core_api_service_present": False,
        "physical_prerequisite.core_api_process_present": False,
        "physical_prerequisite.core_api_listener_present": False,
        "physical_prerequisite.result": "BLOCKED_PREREQUISITE",
        "physical_prerequisite.historical_phase_deployment_attempted": False,
        "physical_prerequisite.satellite_install_attempted": False,
        "migration.revision": "20260820_0006",
        "migration.down_revision": "20260820_0005",
        "migration.github_postgresql_required": True,
        "tests.ruff": "PASS",
        "tests.format": "PASS",
        "tests.mypy": "PASS",
        "tests.governance": "PASS",
        "tests.non_integration_passed": 465,
        "tests.postgresql_deselected_local": 36,
        "phase10": "NOT_STARTED",
    }.items():
        _equal(data, path, expected)

    physical = _get(data, "physical_tool_gate")
    if not isinstance(physical, Mapping) or set(physical) != PHYSICAL_TOOL_KEYS:
        raise ValueError("physical tool gate shape is invalid")
    if any(value != "NOT_RUN_PREREQUISITE" for value in physical.values()):
        raise ValueError("blocked physical gates must not be represented as pass")

    final_ci = _get(data, "ci.final_exact_head")
    if final_ci != {
        "required": True,
        "verification": "EXTERNAL_GITHUB_CHECK_REQUIRED",
    }:
        raise ValueError("final exact-head CI must remain an external governance check")


if __name__ == "__main__":
    validate()
    print("Phase 9 evidence validation passed.")
