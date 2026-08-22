"""Validate sanitized Phase 10 software and physical voice evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "phase",
    "base_main_sha",
    "governance_correction_commit",
    "software_tested_commit",
    "physical_voice_tested_commit",
    "final_head",
    "status",
    "software",
    "physical_gate",
    "dependencies",
    "privacy",
    "regressions",
    "phase_11_boundary",
}
REQUIRED_SOFTWARE = {
    "unit_tests",
    "lint",
    "typing",
    "governance",
    "no_direct_model_bypass",
}
REQUIRED_PHYSICAL = {
    "status",
    "wake_word",
    "follow_up",
    "silence_timeout",
    "barge_in",
    "ptt_fallback",
    "arabic_stt",
    "english_stt",
    "mixed_language_stt",
    "no_speech_no_model",
    "no_retention_scan",
    "resource_metrics",
    "latency_metrics",
}
REQUIRED_DEPENDENCIES = {
    "wake_word",
    "vad",
    "stt",
    "arabic_tts",
    "english_tts",
    "pipecat",
    "capture_playback",
}
FORBIDDEN_KEYS = {"audio", "pcm", "recording", "credential", "token", "transcript_text"}


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _walk_forbidden(value: Any, path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in FORBIDDEN_KEYS:
                raise ValueError(f"forbidden raw/secrecy field: {path}.{key}")
            _walk_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]")


def validate_evidence(payload: dict[str, Any]) -> None:
    """Reject incomplete, non-sanitized, or contradictory evidence."""

    missing = REQUIRED_TOP_LEVEL - payload.keys()
    if missing:
        raise ValueError(f"missing top-level fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-voice-evidence/v1" or payload["phase"] != 10:
        raise ValueError("unsupported Phase 10 evidence schema")
    if payload["status"] not in {"pending_physical", "pass", "blocked"}:
        raise ValueError("invalid evidence status")
    software = _require_mapping(payload["software"], "software")
    physical = _require_mapping(payload["physical_gate"], "physical_gate")
    dependencies = _require_mapping(payload["dependencies"], "dependencies")
    if missing := REQUIRED_SOFTWARE - software.keys():
        raise ValueError(f"missing software fields: {sorted(missing)}")
    if missing := REQUIRED_PHYSICAL - physical.keys():
        raise ValueError(f"missing physical fields: {sorted(missing)}")
    if missing := REQUIRED_DEPENDENCIES - dependencies.keys():
        raise ValueError(f"missing dependency fields: {sorted(missing)}")
    if physical["status"] not in {"pending", "pass", "blocked"}:
        raise ValueError("invalid physical status")
    if payload["status"] == "pass":
        if physical["status"] != "pass" or not payload["physical_voice_tested_commit"]:
            raise ValueError("overall pass requires physical pass and tested commit")
        for key in REQUIRED_PHYSICAL - {"resource_metrics", "latency_metrics"}:
            if physical[key] is not True:
                raise ValueError(f"physical acceptance field is not true: {key}")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        validate_evidence(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"PHASE_10_EVIDENCE_INVALID: {exc}", file=sys.stderr)
        return 1
    print("PHASE_10_EVIDENCE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
