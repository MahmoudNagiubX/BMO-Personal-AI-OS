from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from scripts.phase_05b.validate_evidence import BGE, QWEN, validate

ROOT = Path(__file__).resolve().parents[3]


def valid_evidence() -> dict[str, object]:
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
    return {
        "schema_version": "phase-05b-model-gateway/v1",
        "tested_git_commit": "a" * 40,
        "venom_hostname": "venom-server",
        "transport": {
            "type": "reverse_ssh",
            "tuf_ollama_listener": "127.0.0.1:11434",
            "venom_listener": "127.0.0.1:11434",
            "public_or_lan_11434": False,
            "ufw_ollama_rule": False,
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
        "venom_resources": {"before": {}, "after": {}, "delta": {}},
    }


def test_complete_sanitized_evidence_validates() -> None:
    assert validate(valid_evidence()) == []


def test_public_listener_and_cloud_fallback_are_rejected() -> None:
    payload = valid_evidence()
    transport = payload["transport"]
    acceptance = payload["acceptance"]
    assert isinstance(transport, dict) and isinstance(acceptance, dict)
    transport["public_or_lan_11434"] = True
    acceptance["cloud_fallback"] = True
    errors = validate(payload)
    assert "loopback-only reverse SSH transport evidence is incomplete" in errors
    assert "security or phase boundary evidence is invalid" in errors


def test_wrong_identity_and_active_nine_b_are_rejected() -> None:
    payload = valid_evidence()
    models = payload["models"]
    assert isinstance(models, dict)
    models["qwen_digest"] = "sha256:" + "0" * 64
    models["qwen_9b"] = "ACTIVE"
    assert "accepted model identity evidence is incomplete" in validate(payload)


def test_overall_claim_cannot_replace_subordinate_evidence() -> None:
    payload = valid_evidence()
    acceptance = payload["acceptance"]
    assert isinstance(acceptance, dict)
    acceptance["overall"] = "PASS"
    acceptance["offline_proof"] = False
    assert "mandatory subordinate acceptance evidence is incomplete" in validate(payload)


def test_sensitive_fields_and_missing_resources_are_rejected() -> None:
    payload = deepcopy(valid_evidence())
    payload["private_key"] = "synthetic"
    payload.pop("venom_resources")
    errors = validate(payload)
    assert "evidence contains a prohibited sensitive field" in errors
    assert "VENOM before/after/delta resource evidence is missing" in errors


def test_tunnel_configuration_is_loopback_only_and_bounded() -> None:
    config = json.loads(
        (ROOT / "infrastructure/tuf/model_gateway/tunnel_config.json").read_text(encoding="utf-8")
    )
    assert config == {
        "schema_version": "phase-05b-reverse-ssh/v1",
        "remote_host": "192.162.1.21",
        "remote_user": "venom",
        "remote_bind": "127.0.0.1:11434",
        "local_target": "127.0.0.1:11434",
        "server_alive_interval_seconds": 15,
        "server_alive_count_max": 3,
        "exit_on_forward_failure": True,
        "batch_mode": True,
        "agent_forwarding": False,
        "x11_forwarding": False,
        "pty": False,
    }


def test_tunnel_identity_and_lifecycle_scripts_remain_restricted() -> None:
    installer = (ROOT / "scripts/phase_05b/install_venom.sh").read_text(encoding="utf-8")
    manager = (ROOT / "infrastructure/tuf/model_gateway/manage_tunnel.ps1").read_text(
        encoding="utf-8"
    )
    assert 'permitlisten="127.0.0.1:11434"' in installer
    assert 'from="192.162.1.2"' in installer
    assert "restrict,port-forwarding" in installer
    assert "bmo-phase05b-tunnel" in installer
    assert "ForwardAgent=no" in manager
    assert "ForwardX11=no" in manager
    assert "ClearAllForwardings" not in manager
    assert "127.0.0.1:11434:127.0.0.1:11434" in manager
    assert "qwen3.5:4b" in manager and QWEN.removeprefix("sha256:") in manager
    assert "bge-m3:567m" in manager and BGE.removeprefix("sha256:") in manager
    assert "0.0.0.0:11434" not in installer + manager
    assert "Stop-Process -Name ssh" not in manager
    task_installer = (ROOT / "infrastructure/tuf/model_gateway/install_tunnel_task.ps1").read_text(
        encoding="utf-8"
    )
    assert "Join-Path $PSScriptRoot 'manage_tunnel.ps1'" in task_installer
    assert "RunLevel Limited" in task_installer
    assert "LogonType Interactive" in task_installer


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
