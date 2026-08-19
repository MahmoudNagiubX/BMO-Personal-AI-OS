"""Validate sanitized Phase 5B physical deployment acceptance evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

QWEN = "sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
BGE = "sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SENSITIVE_KEYS = {
    "password",
    "private_key",
    "secret",
    "token",
    "prompt",
    "response",
    "vector",
    "raw_payload",
}


def _keys(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [str(key) for key in value] + [
            key for child in value.values() for key in _keys(child)
        ]
    if isinstance(value, list):
        return [key for child in value for key in _keys(child)]
    return []


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _nonnegative(value: object) -> bool:
    return _number(value) and value >= 0  # type: ignore[operator]


def _bounded_text(value: object, *, maximum: int = 500) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= maximum


def _timestamp(value: object) -> bool:
    return isinstance(value, str) and UTC_TIMESTAMP.fullmatch(value) is not None


def _validate_transport(payload: Mapping[str, Any], errors: list[str]) -> None:
    transport = _mapping(payload.get("transport"))
    if transport is None or (
        transport.get("type") != "reverse_ssh"
        or transport.get("tunnel_identity_user") != "bmo-tunnel"
        or transport.get("directional_forwarding_policy") != "remote_only"
        or transport.get("tuf_ollama_listener") != "127.0.0.1:11434"
        or transport.get("venom_listener") != "127.0.0.1:11434"
        or transport.get("public_or_lan_11434") is not False
        or transport.get("ufw_ollama_rule") is not False
        or transport.get("dedicated_key_restricted") is not True
        or transport.get("local_forwarding_denied") is not True
        or transport.get("dynamic_forwarding_denied") is not True
        or transport.get("alternate_remote_listen_denied") is not True
        or transport.get("scheduled_task_run_level") != "Limited"
        or transport.get("scheduled_task_stores_password") is not False
    ):
        errors.append("strict remote-only reverse SSH transport evidence is incomplete")


def _validate_models(payload: Mapping[str, Any], errors: list[str]) -> None:
    models = _mapping(payload.get("models"))
    if models is None or (
        models.get("ollama_version") != "0.32.5"
        or models.get("qwen_tag") != "qwen3.5:4b"
        or models.get("qwen_digest") != QWEN
        or models.get("bge_tag") != "bge-m3:567m"
        or models.get("bge_digest") != BGE
        or models.get("bge_dimension") != 1024
        or models.get("qwen_9b") != "DEFERRED_NOT_ACTIVE"
    ):
        errors.append("accepted model identity evidence is incomplete")


def _validate_acceptance(payload: Mapping[str, Any], errors: list[str]) -> None:
    required_truths = (
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
    acceptance = _mapping(payload.get("acceptance"))
    if acceptance is None or any(acceptance.get(field) is not True for field in required_truths):
        errors.append("mandatory acceptance claims are incomplete")
    if acceptance is None or (
        acceptance.get("cloud_fallback") is not False
        or acceptance.get("tool_execution") is not False
        or acceptance.get("phase_6") != "NOT_STARTED"
    ):
        errors.append("security or Phase 6 boundary evidence is invalid")

    health = _mapping(payload.get("health_proofs"))
    if health is None or any(
        not _bounded_text(health.get(name), maximum=160)
        for name in ("available", "degraded", "offline", "recovery")
    ):
        errors.append("available/degraded/offline/recovery details are incomplete")


def _validate_model_operations(payload: Mapping[str, Any], errors: list[str]) -> None:
    generation = _mapping(payload.get("generation"))
    if generation is None or (
        generation.get("success") is not True
        or generation.get("model") != "qwen3.5:4b"
        or not _nonnegative(generation.get("input_usage_count"))
        or not _nonnegative(generation.get("output_usage_count"))
        or not _number(generation.get("latency_ms"))
        or generation.get("latency_ms", 0) <= 0
        or not _bounded_text(generation.get("finish_reason"), maximum=64)
        or ("digest" in generation and generation.get("digest") != QWEN)
    ):
        errors.append("generation evidence is incomplete or invalid")

    embedding = _mapping(payload.get("embedding"))
    if embedding is None or (
        embedding.get("success") is not True
        or embedding.get("model") != "bge-m3:567m"
        or embedding.get("count") != 1
        or embedding.get("dimension") != 1024
        or embedding.get("finite") is not True
        or not _number(embedding.get("latency_ms"))
        or embedding.get("latency_ms", 0) <= 0
        or ("digest" in embedding and embedding.get("digest") != BGE)
    ):
        errors.append("embedding evidence is incomplete or invalid")

    proposal = _mapping(payload.get("tool_proposal"))
    if proposal is None or (
        not _nonnegative(proposal.get("proposal_count"))
        or proposal.get("proposal_count", 0) < 1
        or proposal.get("returned_as_data") is not True
        or proposal.get("execution_authority") is not False
    ):
        errors.append("tool-proposal no-execution evidence is incomplete or invalid")


def _validate_resilience(payload: Mapping[str, Any], errors: list[str]) -> None:
    resilience = _mapping(payload.get("resilience"))
    if resilience is None or (
        resilience.get("circuit_failure_attempts") != 2
        or resilience.get("open_call_attempts") != 0
        or resilience.get("open_reason") != "circuit_open"
        or resilience.get("half_open_probe_success") is not True
        or resilience.get("final_state") != "closed"
    ):
        errors.append("circuit-breaker evidence is incomplete or invalid")
    if resilience is None or (
        resilience.get("concurrency_callers") != 2
        or resilience.get("first_caller_success") is not True
        or resilience.get("second_caller_category") != "busy"
    ):
        errors.append("two-caller concurrency evidence is incomplete or invalid")

    restart = _mapping(payload.get("restart"))
    required_restart_truths = (
        "scheduled_task_start_recovered_tunnel",
        "scheduled_task_stop_removed_listener",
        "ollama_stop_reported_offline",
        "ollama_start_recovered_available",
    )
    if restart is None or (
        any(restart.get(name) is not True for name in required_restart_truths)
        or restart.get("probe_service_restart") != "success"
        or restart.get("venom_reboot_performed") is not False
        or restart.get("tuf_reboot_performed") is not False
    ):
        errors.append("restart evidence is incomplete or invalid")

    observability = _mapping(payload.get("observability"))
    if observability is None or (
        observability.get("timer_active") is not True
        or observability.get("offline_service_result") != "success"
        or observability.get("available_service_result") != "success"
        or observability.get("failed_units_after_closeout") != 0
        or observability.get("content_retained") is not False
    ):
        errors.append("observability evidence is incomplete or invalid")


def _valid_resource_snapshot(value: object, *, after: bool = False) -> bool:
    snapshot = _mapping(value)
    if snapshot is None or not snapshot:
        return False
    required = (
        "memory_available_bytes",
        "swap_used_bytes",
        "root_used_bytes",
        "root_used_percent",
        "maximum_observed_temperature_c",
        "load_1",
    )
    if not _timestamp(snapshot.get("timestamp_utc")) or any(
        not _nonnegative(snapshot.get(name)) for name in required
    ):
        return False
    root_percent = snapshot.get("root_used_percent")
    temperature = snapshot.get("maximum_observed_temperature_c")
    if root_percent is None or root_percent > 100 or temperature is None or temperature > 125:
        return False
    return not after or snapshot.get("persistent_probe_processes") == 0


def _valid_resource_delta(value: object) -> bool:
    delta = _mapping(value)
    required = (
        "memory_available_bytes",
        "swap_used_bytes",
        "root_used_bytes",
        "root_used_percent",
        "maximum_observed_temperature_c",
        "load_1",
    )
    return delta is not None and bool(delta) and all(_number(delta.get(name)) for name in required)


def _validate_resources(payload: Mapping[str, Any], errors: list[str]) -> None:
    resources = _mapping(payload.get("venom_resources"))
    if resources is None or (
        not _valid_resource_snapshot(resources.get("before"))
        or not _valid_resource_snapshot(resources.get("after"), after=True)
        or not _valid_resource_delta(resources.get("delta"))
    ):
        errors.append("concrete VENOM before/after/delta resource evidence is incomplete")


def _validate_security_and_rollback(payload: Mapping[str, Any], errors: list[str]) -> None:
    security = _mapping(payload.get("security"))
    if security is None or (
        security.get("tuf_non_loopback_11434") is not False
        or security.get("venom_non_loopback_11434") is not False
        or security.get("venom_ufw_default_incoming") != "deny"
        or security.get("venom_ufw_ssh_scope") != "192.162.1.0/24"
        or security.get("venom_public_api_added") is not False
        or security.get("cloud_provider_added") is not False
        or security.get("private_material_recorded") is not False
        or security.get("admin_ssh_available") is not True
        or security.get("root_ssh_denied") is not True
    ):
        errors.append("security closeout evidence is incomplete or invalid")

    rollback = _mapping(payload.get("rollback"))
    if rollback is None or (
        not _bounded_text(rollback.get("tuf"))
        or not _bounded_text(rollback.get("venom"))
        or rollback.get("models_deleted") is not False
        or rollback.get("phase_1_monitor_changed") is not False
    ):
        errors.append("bounded rollback evidence is incomplete or invalid")

    monitor = _mapping(payload.get("phase_1_monitor"))
    if monitor is None or (
        not _timestamp(monitor.get("latest_timestamp_utc"))
        or not _number(monitor.get("temperature_c"))
        or not -40 <= monitor.get("temperature_c", 200) <= 125
        or not _nonnegative(monitor.get("root_used_percent"))
        or monitor.get("root_used_percent", 101) > 100
        or any(
            monitor.get(name) != 0
            for name in (
                "smart_reallocated_sectors",
                "smart_pending_sectors",
                "smart_offline_uncorrectable_sectors",
            )
        )
        or monitor.get("stability_windows") != "WAITING_WITH_OWNER_WAIVER_STILL_MONITORING"
    ):
        errors.append("Phase 1 monitor evidence is incomplete or invalid")


def validate(payload: object) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["evidence must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != "phase-05b-model-gateway/v1":
        errors.append("unsupported Phase 5B evidence schema")
    if any(key.casefold() in SENSITIVE_KEYS for key in _keys(payload)):
        errors.append("evidence contains a prohibited sensitive field")
    tested = payload.get("tested_git_commit")
    if not isinstance(tested, str) or not COMMIT.fullmatch(tested):
        errors.append("tested exact Git commit is malformed")
    tooling = payload.get("tuf_tooling_git_commit")
    if not isinstance(tooling, str) or not COMMIT.fullmatch(tooling):
        errors.append("TUF tooling Git commit is malformed")
    if payload.get("venom_hostname") != "venom-server":
        errors.append("VENOM hostname is invalid")

    _validate_transport(payload, errors)
    _validate_models(payload, errors)
    _validate_acceptance(payload, errors)
    _validate_model_operations(payload, errors)
    _validate_resilience(payload, errors)
    _validate_resources(payload, errors)
    _validate_security_and_rollback(payload, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=invalid evidence input: {type(exc).__name__}")
        return 1
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"ERROR={error}")
        return 1
    print("Phase 5B deployment evidence accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
