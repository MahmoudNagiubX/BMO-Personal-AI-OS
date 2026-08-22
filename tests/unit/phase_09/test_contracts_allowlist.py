from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai_os.identity.contracts import (
    ACTIVE_DEVICE_SCOPES,
    PHASE_6_SCOPES,
    PHASE_7_SCOPES,
    PHASE_8_SCOPES,
    PHASE_9_SCOPES,
)
from personal_ai_os.satellites.windows.allowlist import WindowsAllowlist
from personal_ai_os.satellites.windows.config import WindowsSatelliteSettings
from personal_ai_os.satellites.windows.contracts import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    SatelliteHello,
)
from personal_ai_os.tools.contracts import ApprovalPolicy, RiskLevel, SandboxPolicy
from personal_ai_os.tools.registry import default_registry


def _document(root: Path) -> dict[str, object]:
    executable = Path(__import__("sys").executable)
    script = root / "workflow.py"
    script.write_text("from pathlib import Path\nPath('done.marker').touch()\n")
    project = root / "project"
    project.mkdir()
    search = root / "search"
    search.mkdir()
    return {
        "schema_version": "phase-09-windows-allowlist/v1",
        "apps": [
            {
                "app_id": "editor",
                "executable": str(executable),
                "fixed_args": ["--version"],
                "working_directory": str(root),
                "observe_process": False,
            }
        ],
        "projects": [
            {
                "project_id": "bmo",
                "executable": str(executable),
                "fixed_args": ["--version"],
                "working_directory": str(root),
                "project_directory": str(project),
            }
        ],
        "search_roots": [{"root_id": "documents", "directory": str(search), "max_entries": 100}],
        "workflows": [
            {
                "workflow_id": "bounded",
                "executable": str(executable),
                "fixed_args": [],
                "working_directory": str(root),
                "script": str(script),
                "timeout_seconds": 10,
                "expected_exit_codes": [0],
                "allow_hard_stop": False,
                "verification": {
                    "kind": "marker_file_exists",
                    "path": str(root / "done.marker"),
                },
            }
        ],
    }


def test_phase_scopes_are_additive_and_narrow() -> None:
    assert frozenset({"satellite.connect"}) == PHASE_9_SCOPES
    assert PHASE_6_SCOPES | PHASE_7_SCOPES | PHASE_8_SCOPES | PHASE_9_SCOPES == (
        ACTIVE_DEVICE_SCOPES
    )
    assert "tool.execute" not in ACTIVE_DEVICE_SCOPES


def test_wire_contract_rejects_wrong_version_duplicates_and_extra_fields() -> None:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "connection_id": uuid4(),
        "software_version": "phase09-test",
        "capabilities": ["windows.telemetry.read"],
        "sent_at": datetime.now(UTC),
    }
    assert SatelliteHello.model_validate(payload, strict=True).protocol_version == PROTOCOL_VERSION
    with pytest.raises(ValidationError):
        SatelliteHello.model_validate({**payload, "protocol_version": "future"}, strict=True)
    with pytest.raises(ValidationError):
        SatelliteHello.model_validate(
            {**payload, "capabilities": ["windows.telemetry.read"] * 2}, strict=True
        )
    with pytest.raises(ValidationError):
        SatelliteHello.model_validate({**payload, "credential": "forbidden"}, strict=True)
    assert MAX_FRAME_BYTES == 16_384


def test_allowlist_is_strict_fixed_and_capability_derived(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(_document(tmp_path)), encoding="utf-8")
    allowlist = WindowsAllowlist.load(path)
    assert allowlist.apps["editor"].fixed_args == ["--version"]
    assert allowlist.available_capabilities() == frozenset(
        {
            "windows.telemetry.read",
            "windows.media.control",
            "windows.files.search",
            "windows.app.open",
            "windows.project.open",
            "windows.workflow.start",
        }
    )

    duplicate = path.read_text(encoding="utf-8").replace(
        '"schema_version":', '"schema_version":"phase-09-windows-allowlist/v1","schema_version":'
    )
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        WindowsAllowlist.load(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["apps"][0].update(executable="relative.exe"),
        lambda data: data["apps"][0].update(fixed_args=["ok\nmalicious"]),
        lambda data: data["apps"].append(dict(data["apps"][0])),
        lambda data: data.update(unknown="forbidden"),
    ],
)
def test_allowlist_rejects_dynamic_or_ambiguous_authority(tmp_path: Path, mutation: object) -> None:
    data = _document(tmp_path)
    mutation(data)  # type: ignore[operator]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises((ValueError, ValidationError)):
        WindowsAllowlist.load(path)


def test_registry_fixes_windows_policy_and_preserves_phase8() -> None:
    registry = default_registry()
    assert registry.resolve("phase8.status.read", 1).execution_target == (
        "synthetic_phase8_executor"
    )
    workflow = registry.resolve("windows.workflow.start", 1)
    assert workflow.risk_level is RiskLevel.CONSEQUENTIAL
    assert workflow.approval_policy is ApprovalPolicy.EXACT_OWNER
    assert workflow.sandbox_policy is SandboxPolicy.SATELLITE_TYPED
    assert workflow.execution_target == "windows_satellite_executor"
    assert workflow.required_device_capabilities == frozenset({"windows.workflow.start"})
    assert registry.resolve("windows.files.search", 1).input_model.model_validate(
        {"root_id": "documents", "query": "report", "max_results": 5}, strict=True
    )


def test_endpoint_requires_tls_except_loopback(tmp_path: Path) -> None:
    settings = WindowsSatelliteSettings(
        endpoint="ws://127.0.0.1/api/v1/satellites/windows/connect",
        allowlist_path=tmp_path / "allowlist.json",
        state_root=tmp_path,
    )
    assert settings.endpoint.startswith("ws://127.0.0.1")
    with pytest.raises(ValidationError, match="must use wss"):
        WindowsSatelliteSettings(
            endpoint="ws://192.0.2.10/api/v1/satellites/windows/connect",
            allowlist_path=tmp_path / "allowlist.json",
            state_root=tmp_path,
        )
    with pytest.raises(ValidationError):
        SatelliteHello(
            protocol_version=PROTOCOL_VERSION,
            connection_id=uuid4(),
            software_version="phase09-test",
            capabilities=["windows.telemetry.read"],
            sent_at=datetime.now(UTC) - timedelta(seconds=1),
            secret="no",  # type: ignore[call-arg]
        )
