from __future__ import annotations

from pathlib import Path

STOP_SCRIPT = Path("infrastructure/tuf/stop_phase_04_ollama.ps1")


def test_stop_script_ignores_non_listening_tcp_rows() -> None:
    source = STOP_SCRIPT.read_text(encoding="utf-8")
    assert "-State Listen" in source
    assert "Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue" not in source


def test_stop_script_requires_process_listener_and_health_postconditions() -> None:
    source = STOP_SCRIPT.read_text(encoding="utf-8")
    assert "Test-Phase4HealthUnavailable" in source
    assert "-not $stillRunning" in source
    assert "$listeners.Count -eq 0" in source
    assert "api/version" in source


def test_stop_script_verifies_recorded_process_identity_before_stopping() -> None:
    source = STOP_SCRIPT.read_text(encoding="utf-8")
    assert "Get-ProcessExecutablePath -ProcessId $phase4Pid" in source
    assert "The recorded PID does not belong to the dedicated Phase 4 Ollama binary." in source
