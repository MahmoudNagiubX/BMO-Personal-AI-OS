"""Validate sanitized Phase 8.5 advanced-provider evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/phase_reports/evidence/PHASE_08_5_LLAMA_CPP.json"
MANIFEST = ROOT / "infrastructure/tuf/model_manifest.json"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_KEYS = {
    "password",
    "secret",
    "private_key",
    "credential",
    "authorization",
    "raw_prompt",
    "raw_response",
    "raw_model_output",
    "database_url",
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
    elif isinstance(value, str) and ("C:\\Users\\" in value or value.startswith("/home/")):
        raise ValueError(f"unsanitized local path: {path}")


def validate(data: Mapping[str, Any] | None = None) -> None:
    if data is None:
        data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("evidence root must be an object")
    _reject_sensitive(data)
    _equal(data, "schema_version", "phase-08-5-llama-cpp/v1")
    _equal(data, "phase", "phase-08-5")
    implementation_commit = _get(data, "tested_implementation_commit")
    if not isinstance(implementation_commit, str) or not COMMIT.fullmatch(implementation_commit):
        raise ValueError("tested_implementation_commit must be a full commit SHA")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    profile = manifest["advanced_llama_cpp"]
    for path, expected in {
        "runtime.provider": profile["provider"],
        "runtime.build": profile["build"],
        "runtime.server_executable_sha256": profile["server_executable_sha256"],
        "runtime.gguf_sha256": profile["gguf_sha256"],
        "runtime.endpoint": profile["endpoint"],
        "runtime.model_id": profile["model_id"],
        "runtime.gguf_filename": profile["gguf_filename"],
        "runtime.n_safe_gpu_layers": profile["n_gpu_layers"],
        "runtime.context_tokens": profile["context_tokens"],
        "runtime.kv_cache_type": profile["kv_cache_type"],
        "runtime.parallel": profile["parallel"],
        "runtime.vision": profile["vision"],
        "runtime.loopback_only": profile["loopback_only"],
        "runtime.no_cloud_fallback": profile["no_cloud_fallback"],
    }.items():
        _equal(data, path, expected)
    for path, expected in {
        "acceptance.rest_stress.result": "PASS",
        "acceptance.rest_stress.pass_count": 25,
        "acceptance.rest_stress.fail_count": 0,
        "acceptance.rest_stress.sleep_unload": True,
        "acceptance.switching.result": "PASS",
        "acceptance.switching.cycles": 10,
        "acceptance.switching.advanced_pass": 10,
        "acceptance.switching.fast_pass": 10,
        "acceptance.switching.bge_pass": 10,
        "acceptance.switching.bge_dimension": 1024,
        "acceptance.switching.bge_finite": True,
        "acceptance.switching.no_simultaneous_heavy_residency": True,
        "acceptance.security.tuf_loopback_only": True,
        "acceptance.security.venom_loopback_only": True,
        "acceptance.security.oom_events": 0,
        "acceptance.security.runner_crashes": 0,
        "acceptance.security.display_driver_resets": 0,
        "acceptance.gateway_failure_isolation.advanced_off_fast_generation": "pass",
        "acceptance.gateway_failure_isolation.advanced_off_bge_embedding": "pass",
        "acceptance.gateway_failure_isolation."
        "advanced_unavailable_category": "provider_unavailable",
        "acceptance.gateway_failure_isolation.advanced_unavailable_reason": "provider_offline",
        "acceptance.gateway_failure_isolation.advanced_unavailable_fallback": False,
        "acceptance.gateway_failure_isolation.fast_circuit_after_advanced_failure": "closed",
        "acceptance.gateway_failure_isolation.advanced_restored": "pass",
        "acceptance.cross_host_production.gateway_host": "VENOM",
        "acceptance.cross_host_production.inference_host": "TUF",
        "acceptance.cross_host_production.endpoint": "127.0.0.1:11435",
        "acceptance.cross_host_production.model_filename": profile["gguf_filename"],
        "acceptance.cross_host_production.windows_path_syntax_accepted": True,
        "acceptance.cross_host_production.exact_model_identity": True,
        "acceptance.cross_host_production.advanced_generation": "pass",
        "acceptance.cross_host_production.advanced_off_fast_generation": "pass",
        "acceptance.cross_host_production.advanced_off_bge_embedding": "pass",
        "acceptance.cross_host_production.no_simultaneous_heavy_residency": True,
        "repository.phase_9": "NOT_STARTED",
        "ci.final_exact_head.required": True,
        "ci.final_exact_head.verification": "EXTERNAL_GITHUB_CHECK_REQUIRED",
    }.items():
        _equal(data, path, expected)
    final_ci = _get(data, "ci.final_exact_head")
    if set(final_ci) != {"required", "verification"}:
        raise ValueError("final exact-head CI must not self-attest commit, status, or run")


if __name__ == "__main__":
    validate()
    print("Phase 8.5 evidence validation passed.")
