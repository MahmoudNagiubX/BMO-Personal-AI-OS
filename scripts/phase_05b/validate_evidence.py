"""Validate sanitized Phase 5B physical deployment acceptance evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

QWEN = "sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd"
BGE = "sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
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


def validate(payload: object) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["evidence must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != "phase-05b-model-gateway/v1":
        errors.append("unsupported Phase 5B evidence schema")
    if any(key.casefold() in SENSITIVE_KEYS for key in _keys(payload)):
        errors.append("evidence contains a prohibited sensitive field")
    if payload.get("tested_git_commit") is None:
        errors.append("tested exact Git commit is missing")
    if payload.get("venom_hostname") != "venom-server":
        errors.append("VENOM hostname is invalid")

    transport = payload.get("transport")
    if not isinstance(transport, Mapping) or (
        transport.get("type") != "reverse_ssh"
        or transport.get("tuf_ollama_listener") != "127.0.0.1:11434"
        or transport.get("venom_listener") != "127.0.0.1:11434"
        or transport.get("public_or_lan_11434") is not False
        or transport.get("ufw_ollama_rule") is not False
    ):
        errors.append("loopback-only reverse SSH transport evidence is incomplete")

    models = payload.get("models")
    if not isinstance(models, Mapping) or (
        models.get("ollama_version") != "0.32.5"
        or models.get("qwen_tag") != "qwen3.5:4b"
        or models.get("qwen_digest") != QWEN
        or models.get("bge_tag") != "bge-m3:567m"
        or models.get("bge_digest") != BGE
        or models.get("bge_dimension") != 1024
        or models.get("qwen_9b") != "DEFERRED_NOT_ACTIVE"
    ):
        errors.append("accepted model identity evidence is incomplete")

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
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping) or any(
        acceptance.get(field) is not True for field in required_truths
    ):
        errors.append("mandatory subordinate acceptance evidence is incomplete")
    if not isinstance(acceptance, Mapping) or (
        acceptance.get("cloud_fallback") is not False
        or acceptance.get("tool_execution") is not False
        or acceptance.get("phase_6") != "NOT_STARTED"
    ):
        errors.append("security or phase boundary evidence is invalid")

    resources = payload.get("venom_resources")
    if not isinstance(resources, Mapping) or not all(
        isinstance(resources.get(name), Mapping) for name in ("before", "after", "delta")
    ):
        errors.append("VENOM before/after/delta resource evidence is missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"ERROR={error}")
        return 1
    print("Phase 5B deployment evidence accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
