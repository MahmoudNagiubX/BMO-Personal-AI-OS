from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.phase_05b.validate_evidence import BGE, QWEN, validate

ROOT = Path(__file__).resolve().parents[3]
MISSING = object()


def valid_evidence() -> dict[str, Any]:
    truths = {
        name: True
        for name in (
            "available_proof",
            "degraded_proof",
            "offline_proof",
            "recovery_proof",
            "generation_smoke",
            "embedding_smoke",
            "tool_proposal_data_only",
            "retry_circuit_proof",
            "concurrency_proof",
            "tunnel_restart_proof",
            "ollama_restart_proof",
            "observability_proof",
            "resource_acceptance",
            "rollback_documented",
        )
    }
    truths.update(cloud_fallback=False, tool_execution=False, phase_6="NOT_STARTED")
    snapshot = {
        "timestamp_utc": "2026-08-19T01:28:32Z",
        "memory_available_bytes": 3_540_463_616,
        "swap_used_bytes": 0,
        "root_used_bytes": 8_399_044_608,
        "root_used_percent": 9,
        "maximum_observed_temperature_c": 51.0,
        "load_1": 0.06,
    }
    return {
        "schema_version": "phase-05b-model-gateway/v1",
        "tested_git_commit": "a" * 40,
        "tuf_tooling_git_commit": "b" * 40,
        "venom_hostname": "venom-server",
        "transport": {
            "type": "reverse_ssh",
            "tunnel_identity_user": "bmo-tunnel",
            "directional_forwarding_policy": "remote_only",
            "tuf_ollama_listener": "127.0.0.1:11434",
            "venom_listener": "127.0.0.1:11434",
            "public_or_lan_11434": False,
            "ufw_ollama_rule": False,
            "dedicated_key_restricted": True,
            "local_forwarding_denied": True,
            "dynamic_forwarding_denied": True,
            "alternate_remote_listen_denied": True,
            "scheduled_task_run_level": "Limited",
            "scheduled_task_stores_password": False,
        },
        "models": {
            "ollama_version": "0.32.5",
            "qwen_tag": "qwen3.5:4b",
            "qwen_digest": QWEN,
            "bge_tag": "bge-m3:567m",
            "bge_digest": BGE,
            "bge_dimension": 1024,
            "qwen_9b": "DEFERRED_NOT_ACTIVE",
        },
        "acceptance": truths,
        "health_proofs": {
            "available": "ready with exact provider and model identities",
            "degraded": "isolated expected-version mismatch",
            "offline": "provider unavailable after two bounded attempts",
            "recovery": "available after canonical tunnel restoration",
        },
        "generation": {
            "success": True,
            "model": "qwen3.5:4b",
            "latency_ms": 7029.044,
            "input_usage_count": 20,
            "output_usage_count": 3,
            "finish_reason": "stop",
        },
        "embedding": {
            "success": True,
            "model": "bge-m3:567m",
            "count": 1,
            "dimension": 1024,
            "finite": True,
            "latency_ms": 4153.548,
        },
        "tool_proposal": {
            "proposal_count": 1,
            "returned_as_data": True,
            "execution_authority": False,
        },
        "resilience": {
            "circuit_failure_attempts": 2,
            "open_call_attempts": 0,
            "open_reason": "circuit_open",
            "half_open_probe_success": True,
            "final_state": "closed",
            "concurrency_callers": 2,
            "first_caller_success": True,
            "second_caller_category": "busy",
        },
        "restart": {
            "scheduled_task_start_recovered_tunnel": True,
            "scheduled_task_stop_removed_listener": True,
            "ollama_stop_reported_offline": True,
            "ollama_start_recovered_available": True,
            "probe_service_restart": "success",
            "venom_reboot_performed": False,
            "tuf_reboot_performed": False,
        },
        "observability": {
            "timer_active": True,
            "offline_service_result": "success",
            "available_service_result": "success",
            "failed_units_after_closeout": 0,
            "content_retained": False,
        },
        "venom_resources": {
            "before": snapshot,
            "after": {
                **snapshot,
                "timestamp_utc": "2026-08-19T01:53:44Z",
                "persistent_probe_processes": 0,
            },
            "delta": {
                "memory_available_bytes": 5_382_144,
                "swap_used_bytes": 0,
                "root_used_bytes": 39_358_464,
                "root_used_percent": 0,
                "maximum_observed_temperature_c": 1.0,
                "load_1": 0.07,
            },
        },
        "phase_1_monitor": {
            "latest_timestamp_utc": "2026-08-19T01:42:39Z",
            "temperature_c": 43.0,
            "root_used_percent": 9,
            "smart_reallocated_sectors": 0,
            "smart_pending_sectors": 0,
            "smart_offline_uncorrectable_sectors": 0,
            "stability_windows": "WAITING_WITH_OWNER_WAIVER_STILL_MONITORING",
        },
        "security": {
            "tuf_non_loopback_11434": False,
            "venom_non_loopback_11434": False,
            "venom_ufw_default_incoming": "deny",
            "venom_ufw_ssh_scope": "192.162.1.0/24",
            "venom_public_api_added": False,
            "cloud_provider_added": False,
            "private_material_recorded": False,
            "admin_ssh_available": True,
            "root_ssh_denied": True,
        },
        "rollback": {
            "tuf": "stop and remove only the limited task and exact managed tunnel",
            "venom": "remove only the Phase 5B tunnel identity, match policy, and probe deployment",
            "models_deleted": False,
            "phase_1_monitor_changed": False,
        },
    }


def _mutate(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    target = payload
    for name in path[:-1]:
        target = target[name]
    if value is MISSING:
        target.pop(path[-1])
    else:
        target[path[-1]] = value


REJECTION_CASES = (
    ("empty-resources", ("venom_resources",), {"before": {}, "after": {}, "delta": {}}, "resource"),
    ("missing-generation", ("generation",), MISSING, "generation"),
    ("generation-failed", ("generation", "success"), False, "generation"),
    ("wrong-generation-model", ("generation", "model"), "wrong", "generation"),
    ("missing-embedding", ("embedding",), MISSING, "embedding"),
    ("wrong-embedding-dimension", ("embedding", "dimension"), 768, "embedding"),
    ("nonfinite-embedding-proof", ("embedding", "finite"), False, "embedding"),
    ("missing-tool-proposal", ("tool_proposal",), MISSING, "tool-proposal"),
    ("tool-execution-authority", ("tool_proposal", "execution_authority"), True, "tool-proposal"),
    ("missing-circuit", ("resilience",), MISSING, "circuit-breaker"),
    ("wrong-circuit-attempts", ("resilience", "circuit_failure_attempts"), 1, "circuit-breaker"),
    ("missing-concurrency", ("resilience", "concurrency_callers"), MISSING, "concurrency"),
    ("wrong-busy-category", ("resilience", "second_caller_category"), "unavailable", "concurrency"),
    ("missing-restart", ("restart",), MISSING, "restart"),
    ("failed-system-unit", ("observability", "failed_units_after_closeout"), 1, "observability"),
    ("nonloopback-listener", ("transport", "venom_listener"), "0.0.0.0:11434", "transport"),
    ("missing-local-denial", ("transport", "local_forwarding_denied"), MISSING, "transport"),
    ("missing-dynamic-denial", ("transport", "dynamic_forwarding_denied"), MISSING, "transport"),
    (
        "missing-alternate-listen-denial",
        ("transport", "alternate_remote_listen_denied"),
        MISSING,
        "transport",
    ),
    ("malformed-commit", ("tested_git_commit",), "ABC", "commit"),
    ("cloud-fallback", ("acceptance", "cloud_fallback"), True, "boundary"),
    ("phase-six-started", ("acceptance", "phase_6"), "STARTED", "boundary"),
    ("sensitive-field", ("private_key",), "synthetic", "sensitive"),
)


def test_complete_sanitized_evidence_validates() -> None:
    assert validate(valid_evidence()) == []


@pytest.mark.parametrize(
    ("_name", "path", "value", "expected"),
    REJECTION_CASES,
    ids=[case[0] for case in REJECTION_CASES],
)
def test_required_incomplete_or_unsafe_evidence_is_rejected(
    _name: str, path: tuple[str, ...], value: object, expected: str
) -> None:
    payload = deepcopy(valid_evidence())
    _mutate(payload, path, value)
    assert any(expected.casefold() in error.casefold() for error in validate(payload))


def test_wrong_identity_and_active_nine_b_are_rejected() -> None:
    payload = valid_evidence()
    payload["models"]["qwen_digest"] = "sha256:" + "0" * 64
    payload["models"]["qwen_9b"] = "ACTIVE"
    assert "accepted model identity evidence is incomplete" in validate(payload)


def test_overall_claim_cannot_replace_subordinate_evidence() -> None:
    payload = valid_evidence()
    payload["acceptance"]["overall"] = "PASS"
    payload["health_proofs"].pop("offline")
    assert "available/degraded/offline/recovery details are incomplete" in validate(payload)


def test_tunnel_configuration_is_loopback_only_and_bounded() -> None:
    config = json.loads(
        (ROOT / "infrastructure/tuf/model_gateway/tunnel_config.json").read_text(encoding="utf-8")
    )
    assert config == {
        "schema_version": "phase-05b-reverse-ssh/v1",
        "remote_host": "192.162.1.21",
        "remote_user": "bmo-tunnel",
        "remote_bind": "127.0.0.1:11434",
        "local_target": "127.0.0.1:11434",
        "server_alive_interval_seconds": 15,
        "server_alive_count_max": 3,
        "exit_on_forward_failure": True,
        "batch_mode": True,
        "agent_forwarding": False,
        "x11_forwarding": False,
        "advanced_remote_bind": "127.0.0.1:11435",
        "advanced_local_target": "127.0.0.1:11435",
        "pty": False,
    }


def test_tunnel_identity_and_lifecycle_scripts_remain_restricted() -> None:
    installer = (ROOT / "scripts/phase_05b/install_venom.sh").read_text(encoding="utf-8")
    manager = (ROOT / "infrastructure/tuf/model_gateway/manage_tunnel.ps1").read_text(
        encoding="utf-8"
    )
    assert "Match User bmo-tunnel" in installer
    assert "AllowTcpForwarding remote" in installer
    assert "PermitOpen none" in installer
    assert "PermitListen 127.0.0.1:11434 127.0.0.1:11435" in installer
    assert "127.0.0.1:11435" in installer
    assert "Match all" in installer
    assert 'from="192.162.1.2"' in installer
    assert "restrict,port-forwarding" in installer
    assert "bmo-phase05b-tunnel" in installer
    assert "ForwardAgent=no" in manager
    assert "ForwardX11=no" in manager
    assert "ClearAllForwardings" not in manager
    assert "127.0.0.1:11434:127.0.0.1:11434" in manager
    assert "127.0.0.1:11435:127.0.0.1:11435" in manager
    assert "qwen3.5:4b" in manager and QWEN.removeprefix("sha256:") in manager
    assert "bge-m3:567m" in manager and BGE.removeprefix("sha256:") in manager
    assert "0.0.0.0:11434" not in installer + manager
    assert "Stop-Process -Name ssh" not in manager
    task_installer = (ROOT / "infrastructure/tuf/model_gateway/install_tunnel_task.ps1").read_text(
        encoding="utf-8"
    )
    assert "System32\\OpenSSH\\ssh.exe" in task_installer
    assert "ExitOnForwardFailure=yes" in task_installer
    assert "127.0.0.1:11434" in task_installer
    assert "RunLevel Limited" in task_installer
    assert "LogonType Interactive" in task_installer

    policy_test = (ROOT / "infrastructure/tuf/model_gateway/test_tunnel_policy.ps1").read_text(
        encoding="utf-8"
    )
    assert "'-L'" in policy_test and "'-D'" in policy_test and "'-R'" in policy_test
    assert "local_forwarding_denied=true" in policy_test
    assert "dynamic_forwarding_denied=true" in policy_test
    assert "alternate_remote_listen_denied=true" in policy_test

    closeout = (ROOT / "scripts/phase_05b/verify_venom_security_closeout.sh").read_text(
        encoding="utf-8"
    )
    assert "/usr/sbin/sshd -t" in closeout
    assert "/usr/sbin/ufw status verbose" in closeout
    assert "PHASE_05B_SECURITY_CLOSEOUT_PASS" in closeout
    assert "systemctl reload" not in closeout and "systemctl restart" not in closeout


def test_probe_is_offline_safe_and_does_not_collect_content() -> None:
    probe = (ROOT / "scripts/phase_05b/probe_gateway.py").read_text(encoding="utf-8")
    service = (
        ROOT / "infrastructure/home_server/systemd/bmo-phase5b-gateway-probe.service"
    ).read_text(encoding="utf-8")
    assert "Offline is an expected capability state" in probe
    assert "return 0" in probe
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    for prohibited in ("prompt", "response", "embedding", "vector", "private_key"):
        assert f'"{prohibited}"' not in probe
