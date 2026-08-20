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
        "C:\\Users\\" in value
        or "C:/Users/" in value
        or value.startswith("/home/")
        or "Bearer " in value
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

    prereq_result = _get(data, "physical_prerequisite.result")
    if prereq_result == "PASS":
        pass_prereqs: dict[str, Any] = {
            "physical_prerequisite.phase5b_release_present": True,
            "physical_prerequisite.phase6_deployment_present": True,
            "physical_prerequisite.phase7_deployment_present": True,
            "physical_prerequisite.phase8_deployment_present": True,
            "physical_prerequisite.postgresql_active": True,
            "physical_prerequisite.core_api_service_present": True,
            "physical_prerequisite.core_api_process_present": True,
            "physical_prerequisite.core_api_listener_present": True,
            "physical_prerequisite.historical_phase_deployment_attempted": False,
            "physical_prerequisite.satellite_install_attempted": False,
        }
        for path, expected in pass_prereqs.items():
            _equal(data, path, expected)
        physical = _get(data, "physical_tool_gate")
        if not isinstance(physical, Mapping) or set(physical) != PHYSICAL_TOOL_KEYS:
            raise ValueError("physical tool gate shape is invalid")
        if any(value != "PASS" for value in physical.values()):
            raise ValueError("all physical tool gates must pass when prerequisite passed")

        # Concrete physical metrics validation
        _equal(data, "protocol.physical_transport", "ws_loopback_over_authenticated_ssh_forward")
        _equal(data, "physical_metrics.listener_bindings.core_api", "127.0.0.1:8000")
        _equal(data, "physical_metrics.listener_bindings.postgresql", "127.0.0.1:5432")
        _equal(data, "physical_metrics.listener_bindings.tuf_satellite_inbound_count", 0)

        idle_cpu = _get(data, "physical_metrics.satellite_resources.idle_cpu_percent")
        idle_ram = _get(data, "physical_metrics.satellite_resources.idle_memory_mb")
        if not isinstance(idle_cpu, (int, float)) or not (0.0 <= idle_cpu <= 5.0):
            raise ValueError("idle_cpu_percent out of expected range")
        if not isinstance(idle_ram, (int, float)) or not (0.0 < idle_ram <= 50.0):
            raise ValueError("idle_memory_mb out of expected range")

        latencies = _get(data, "physical_metrics.tool_latencies_ms")
        for key in (
            "status_read_ms",
            "files_search_ms",
            "media_volume_ms",
            "workflow_execution_ms",
        ):
            val = latencies.get(key)
            if not isinstance(val, (int, float)) or not (0.0 < val < 10000.0):
                raise ValueError(f"latency metric {key} out of range: {val}")

        _equal(data, "physical_metrics.volume_verification.initial_volume", 54)
        _equal(data, "physical_metrics.volume_verification.test_volume", 45)
        _equal(data, "physical_metrics.volume_verification.measured_test_volume", 45)
        _equal(data, "physical_metrics.volume_verification.restored_volume", 54)

        _equal(data, "physical_metrics.inflight_cancellation.workflow_id", "cancellable_workflow")
        _equal(
            data,
            "physical_metrics.inflight_cancellation.process_observed_before_cancel",
            True,
        )
        _equal(
            data,
            "physical_metrics.inflight_cancellation.cancel_requested_status",
            "cancel_requested",
        )
        _equal(data, "physical_metrics.inflight_cancellation.observation_status", "cancelled")
        _equal(data, "physical_metrics.inflight_cancellation.child_process_stopped", True)
        _equal(data, "physical_metrics.inflight_cancellation.completion_marker_created", False)
        _equal(data, "physical_metrics.inflight_cancellation.audit_events_verified", True)

        _equal(
            data,
            "physical_metrics.replay_verification.duplicate_execution_side_effect_prevented",
            True,
        )
        _equal(data, "physical_metrics.replay_verification.initial_count", 0)
        _equal(data, "physical_metrics.replay_verification.count_after_first_execution", 1)
        _equal(data, "physical_metrics.replay_verification.count_after_duplicate_replay", 1)
        _equal(data, "physical_metrics.replay_verification.changed_digest_failed_closed", True)
        _equal(
            data,
            "physical_metrics.replay_verification.interrupted_consequential_uncertain_outcome",
            True,
        )

        _equal(
            data,
            "physical_metrics.revocation_verification.session_failed_on_revocation",
            True,
        )
        _equal(data, "physical_metrics.revocation_verification.admin_access_unaffected", True)
        _equal(data, "physical_metrics.crashes_and_errors_count", 0)

        # Post-test rollback validation
        _equal(
            data,
            "post_test_rollback.target_commit",
            "24297a9c8ce8ce8d386874949aa3d87e0881d9cc",
        )
        _equal(data, "post_test_rollback.target_schema", "20260820_0005")
        _equal(data, "post_test_rollback.service_status", "active")
        _equal(data, "post_test_rollback.ready_endpoint_status", 200)
        _equal(
            data,
            "post_test_rollback.verified_build_sha",
            "24297a9c8ce8ce8d386874949aa3d87e0881d9cc",
        )
    elif prereq_result == "BLOCKED_PREREQUISITE":
        blocked_prereqs: dict[str, Any] = {
            "physical_prerequisite.inspection_mode": "READ_ONLY",
            "physical_prerequisite.phase5b_release_present": True,
            "physical_prerequisite.phase6_deployment_present": False,
            "physical_prerequisite.phase7_deployment_present": False,
            "physical_prerequisite.phase8_deployment_present": False,
            "physical_prerequisite.postgresql_active": False,
            "physical_prerequisite.core_api_service_present": False,
            "physical_prerequisite.core_api_process_present": False,
            "physical_prerequisite.core_api_listener_present": False,
            "physical_prerequisite.historical_phase_deployment_attempted": False,
            "physical_prerequisite.satellite_install_attempted": False,
        }
        for path, expected in blocked_prereqs.items():
            _equal(data, path, expected)
        physical = _get(data, "physical_tool_gate")
        if not isinstance(physical, Mapping) or set(physical) != PHYSICAL_TOOL_KEYS:
            raise ValueError("physical tool gate shape is invalid")
        if any(value != "NOT_RUN_PREREQUISITE" for value in physical.values()):
            raise ValueError("blocked physical gates must not be represented as pass")
    else:
        raise ValueError(f"invalid physical_prerequisite.result: {prereq_result}")

    common_checks: dict[str, Any] = {
        "migration.revision": "20260820_0006",
        "migration.down_revision": "20260820_0005",
        "migration.github_postgresql_required": True,
        "tests.ruff": "PASS",
        "tests.format": "PASS",
        "tests.mypy": "PASS",
        "tests.governance": "PASS",
        "tests.non_integration_passed": 478,
        "tests.postgresql_deselected_local": 36,
        "phase10": "NOT_STARTED",
    }
    for path, expected in common_checks.items():
        _equal(data, path, expected)

    final_ci = _get(data, "ci.final_exact_head")
    if final_ci != {
        "required": True,
        "verification": "EXTERNAL_GITHUB_CHECK_REQUIRED",
    }:
        raise ValueError("final exact-head CI must remain an external governance check")


if __name__ == "__main__":
    validate()
    print("Phase 9 evidence validation passed.")
