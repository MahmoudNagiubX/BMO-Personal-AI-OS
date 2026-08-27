"""Regression tests for Phase 10 physical gate tunnel bootstrap governance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_launcher_tunnel_readiness_deadline_exceeds_connect_timeout() -> None:
    script = (ROOT / "scripts/phase_10/run_local_acceptance.ps1").read_text(encoding="utf-8")

    # ConnectTimeout is 10s; total readiness deadline must be >= 15s
    # to prevent premature launcher timeout
    assert "ConnectTimeout=10" in script
    assert "Elapsed.TotalSeconds -lt 20" in script or "Elapsed.TotalSeconds -lt 15" in script
    assert "for ($attempt = 0; $attempt -lt 20; $attempt++)" not in script


def test_launcher_surfaces_safe_diagnostic_categories() -> None:
    script = (ROOT / "scripts/phase_10/run_local_acceptance.ps1").read_text(encoding="utf-8")

    expected_categories = (
        "SSH_AUTH_FAILED",
        "SSH_HOST_KEY_FAILED",
        "SSH_HOST_UNREACHABLE",
        "LOCAL_PORT_CONFLICT",
        "SSH_FORWARD_FAILED",
        "SSH_TIMEOUT",
        "CORE_UNREACHABLE_OVER_TUNNEL",
    )
    for category in expected_categories:
        assert category in script


def test_launcher_preflights_existing_port_and_verifies_health_live() -> None:
    script = (ROOT / "scripts/phase_10/run_local_acceptance.ps1").read_text(encoding="utf-8")

    assert "health/live" in script
    assert "LOCAL_PORT_CONFLICT" in script
    assert "CORE_UNREACHABLE_OVER_TUNNEL" in script


def test_launcher_uses_a_separate_physical_evidence_checkpoint() -> None:
    script = (ROOT / "scripts/phase_10/run_local_acceptance.ps1").read_text(encoding="utf-8")

    assert "PHASE_10_PHYSICAL_CONVERSATION_LOCAL.json" in script
    assert '"--output", $output' in script
    assert "OWNER_EVIDENCE_EDIT_PRESERVED" in script
    assert "BMO_VOICE_RESUME_STAGE_A" in script


def test_launcher_does_not_leak_private_keys_or_credentials() -> None:
    script = (ROOT / "scripts/phase_10/run_local_acceptance.ps1").read_text(encoding="utf-8")
    lowered = script.casefold()

    assert "password=" not in lowered
    assert "token=" not in lowered
    assert "write-host $key" not in lowered
