from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_satellite_has_no_inbound_listener_firewall_or_generic_execution_surface() -> None:
    files = [
        *sorted((ROOT / "src/personal_ai_os/satellites/windows").glob("*.py")),
        *sorted((ROOT / "scripts/phase_09").glob("*.py")),
        *sorted((ROOT / "infrastructure/tuf/windows_satellite").glob("*.ps1")),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in files)
    for forbidden in (
        "shell=true",
        "new-netfirewallrule",
        "set-netfirewallprofile",
        "httpserver",
        "tcpserver",
        "start-process -verb runas",
        "runlevel highest",
        "unrestricted shell",
        "caller_executable",
        "caller_arguments",
        "caller_pid",
        "allowlist.update",
    ):
        assert forbidden not in combined
    assert "runlevel limited" in combined
    assert "additional_headers" in combined
    assert "windowscredentialstore" in combined


def test_public_tool_api_exposes_no_general_execute_or_remote_allowlist_mutation() -> None:
    route = (ROOT / "src/personal_ai_os/api/routes/tools.py").read_text(encoding="utf-8")
    satellite = (ROOT / "src/personal_ai_os/api/routes/satellites.py").read_text(encoding="utf-8")
    assert '@router.post("/execute")' not in route
    assert "allowlist" not in satellite.casefold()
    assert "arguments: dict" not in route
    assert '"/tool-calls/{tool_call_id}/dispatch"' in route


def test_lifecycle_scripts_do_not_contain_credentials_or_personal_paths() -> None:
    directory = ROOT / "infrastructure/tuf/windows_satellite"
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(directory.glob("*")) if path.is_file()
    ).casefold()
    assert "authorization: bearer" not in combined
    assert "enrollment code" not in combined
    assert "credential=" not in combined
    assert "c:\\users\\mahmo" not in combined
    assert "register-scheduledtask" in combined
    assert "atlogon" in combined


def test_phase_10_boundary_is_single_device_and_phase_11_is_deferred() -> None:
    phase = (ROOT / "docs/phases/PHASE_09_WINDOWS_SATELLITE.md").read_text(encoding="utf-8")
    assert "single-device JARVIS Voice Core" in phase
    assert "Phase 11 room/multi-device voice remains `NOT_STARTED`" in phase
