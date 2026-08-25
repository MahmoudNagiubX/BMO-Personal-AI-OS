"""Validate sanitized Phase 10 software and physical voice evidence."""

from __future__ import annotations

import argparse
import json
import re
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
    "single_utterance_preroll",
    "right_ctrl_activation",
    "smart_turn_natural_pause",
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
REQUIRED_OWNER_GATE_POLICY = {
    "positive_wake_activations_min",
    "positive_wake_activations_max",
    "representative_negative_cases_max",
    "no_20_round_owner_calibration",
    "single_utterance_preroll",
    "right_ctrl_shared_pipeline",
    "smart_turn_natural_pause",
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
SHA_FIELDS = {
    "base_main_sha",
    "governance_correction_commit",
    "software_tested_commit",
    "final_head",
}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

V2_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "phase",
    "architecture_version",
    "base_main_sha",
    "wake_word",
    "wake_backend",
    "wake_backend_history",
    "microWakeWord_historical_failure",
    "software",
    "physical",
    "privacy",
    "phase_11_boundary",
}
V2_REQUIRED_SOFTWARE = {
    "personalized_mfcc_dtw_adapter",
    "mfcc_weight_free",
    "derived_template_profile",
    "streaming_subsequence_dtw",
    "command_following_wake",
    "enrollment_profile_integrity",
    "no_ambiguous_local_wake_model",
    "synthetic_benchmark",
    "shared_activation_router",
    "right_ctrl_double_tap",
    "ptt_shared_pipeline",
    "in_memory_preroll",
    "silero_vad",
    "smart_turn_v3_local",
    "bounded_timeout_fallback",
    "authenticated_core_only",
    "truthful_response_event_path",
    "safe_phrase_tts_stream",
    "barge_in_cancellation",
    "voice_presentation_policy",
    "latency_resource_metrics_schema",
    "no_direct_model_bypass",
    "calibrated_microphone_presence_gate",
    "wake_backend_comparison",
}
V2_REQUIRED_PRIVACY = {
    "raw_audio_persisted",
    "raw_audio_logged",
    "raw_audio_in_git",
    "raw_audio_in_database",
    "raw_audio_in_audit",
    "bounded_buffers_cleared",
    "credential_in_evidence",
}


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


def _validate_v1_evidence(payload: dict[str, Any]) -> None:
    """Reject incomplete, non-sanitized, or contradictory v1 evidence."""

    missing = REQUIRED_TOP_LEVEL - payload.keys()
    if missing:
        raise ValueError(f"missing top-level fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-voice-evidence/v1" or payload["phase"] != 10:
        raise ValueError("unsupported Phase 10 evidence schema")
    for field in SHA_FIELDS:
        value = payload[field]
        if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
            raise ValueError(f"{field} must be a full lowercase Git SHA")
    physical_commit = payload["physical_voice_tested_commit"]
    if physical_commit is not None and (
        not isinstance(physical_commit, str) or not SHA_PATTERN.fullmatch(physical_commit)
    ):
        raise ValueError("physical_voice_tested_commit must be null or a full lowercase Git SHA")
    if payload["status"] not in {"pending_physical", "pass", "blocked"}:
        raise ValueError("invalid evidence status")
    software = _require_mapping(payload["software"], "software")
    physical = _require_mapping(payload["physical_gate"], "physical_gate")
    dependencies = _require_mapping(payload["dependencies"], "dependencies")
    if missing := REQUIRED_SOFTWARE - software.keys():
        raise ValueError(f"missing software fields: {sorted(missing)}")
    if missing := REQUIRED_PHYSICAL - physical.keys():
        raise ValueError(f"missing physical fields: {sorted(missing)}")
    policy = _require_mapping(physical.get("owner_gate_policy"), "physical_gate.owner_gate_policy")
    if missing := REQUIRED_OWNER_GATE_POLICY - policy.keys():
        raise ValueError(f"missing owner gate policy fields: {sorted(missing)}")
    if policy["positive_wake_activations_min"] != 3:
        raise ValueError("owner wake policy must require at least 3 activations")
    if policy["positive_wake_activations_max"] != 5:
        raise ValueError("owner wake policy must cap activations at 5")
    if policy["representative_negative_cases_max"] != 5:
        raise ValueError("owner wake policy must keep negative cases bounded")
    if policy["no_20_round_owner_calibration"] is not True:
        raise ValueError("owner gate must not require 20-round calibration")
    for field in (
        "single_utterance_preroll",
        "right_ctrl_shared_pipeline",
        "smart_turn_natural_pause",
    ):
        if policy[field] is not True:
            raise ValueError(f"owner gate policy must require {field}")
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
    if "software_tested_commit" in payload:
        value = payload["software_tested_commit"]
        if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
            raise ValueError("software_tested_commit must be a full lowercase Git SHA")
    if "final_exact_head_ci" in payload:
        ci = _require_mapping(payload["final_exact_head_ci"], "final_exact_head_ci")
        if ci.get("status") != "external_github_check_required":
            raise ValueError("v2 exact-head CI must remain an external governance check")
        if ci.get("commit") is not None or ci.get("run") is not None:
            raise ValueError("v2 evidence must not self-attest final exact-head CI")
    _walk_forbidden(payload)


def _validate_v2_evidence(payload: dict[str, Any]) -> None:
    missing = V2_REQUIRED_TOP_LEVEL - payload.keys()
    if missing:
        raise ValueError(f"missing v2 top-level fields: {sorted(missing)}")
    if payload["phase"] != 10 or payload["architecture_version"] != "2":
        raise ValueError("unsupported Phase 10 v2 evidence")
    if payload["schema_version"] != "phase-10-voice-v2-evidence/v1":
        raise ValueError("unsupported Phase 10 v2 evidence schema")
    if payload["wake_word"] != "Jarvis" or payload["wake_backend"] != "personalized_mfcc_dtw":
        raise ValueError("v2 evidence must use exact Jarvis with personalized MFCC DTW")
    base_sha = payload["base_main_sha"]
    if not isinstance(base_sha, str) or not SHA_PATTERN.fullmatch(base_sha):
        raise ValueError("base_main_sha must be a full lowercase Git SHA")
    failure = _require_mapping(
        payload["microWakeWord_historical_failure"], "microWakeWord_historical_failure"
    )
    if failure.get("status") != "confirmed_defective":
        raise ValueError("microWakeWord historical failure must remain confirmed_defective")
    if failure.get("raw_audio_retained") is not False:
        raise ValueError("microWakeWord diagnostics must be non-retaining")
    history = _require_mapping(payload["wake_backend_history"], "wake_backend_history")
    required_history = {
        "openwakeword",
        "microwakeword",
        "vosk",
        "sherpa_kws",
        "pocketsphinx",
        "local_wake_embedding",
    }
    if missing := required_history - history.keys():
        raise ValueError(f"missing historical wake backend fields: {sorted(missing)}")
    software = _require_mapping(payload["software"], "software")
    if missing := V2_REQUIRED_SOFTWARE - software.keys():
        raise ValueError(f"missing v2 software fields: {sorted(missing)}")
    for field in V2_REQUIRED_SOFTWARE - {"synthetic_benchmark", "wake_backend_comparison"}:
        if software[field] is not True:
            raise ValueError(f"v2 software field is not true: {field}")
    if software["synthetic_benchmark"] not in {
        "pending_local_model_artifact",
        "pass_with_hard_negative_overlap",
        "pass",
    }:
        raise ValueError("invalid v2 synthetic benchmark state")
    metrics = _require_mapping(
        software.get("synthetic_benchmark_metrics"), "synthetic_benchmark_metrics"
    )
    for field in (
        "positive_attempts",
        "positive_detections",
        "hard_negative_attempts",
        "false_activations",
        "raw_audio_retained",
        "profile_retained",
        "streaming_subsequence_checked",
        "command_following_checked",
    ):
        if field not in metrics:
            raise ValueError(f"missing MFCC viability metric: {field}")
    if metrics["raw_audio_retained"] is not False or metrics["profile_retained"] is not False:
        raise ValueError("MFCC viability must not retain audio or the temporary profile")
    comparison = _require_mapping(
        software.get("wake_backend_comparison"), "wake_backend_comparison"
    )
    if comparison.get("schema_version") != "phase-10-wake-backend-comparison/v1":
        raise ValueError("invalid wake backend comparison schema")
    comparison_commit = comparison.get("comparison_script_commit")
    if not isinstance(comparison_commit, str) or not SHA_PATTERN.fullmatch(comparison_commit):
        raise ValueError("comparison_script_commit must be a full lowercase Git SHA")
    if comparison.get("wake_word") != "Jarvis":
        raise ValueError("wake backend comparison must use exact Jarvis")
    if comparison.get("wakeforge_revision") != ("1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7"):
        raise ValueError("WakeForge comparison revision is not the audited upstream revision")
    if comparison.get("wakeforge_license") != "Apache-2.0":
        raise ValueError("WakeForge comparison license is not approved")
    if comparison.get("owner_enrollment_justified") is not False:
        raise ValueError("wake comparison must not authorize owner enrollment")
    if comparison.get("winner") != "none":
        raise ValueError("wake comparison winner must remain none until the operating point passes")
    source_policy = _require_mapping(comparison.get("source_policy"), "comparison.source_policy")
    for field in (
        "hugging_face_datasets_used",
        "cloud_tts_used",
        "voice_conversion_used",
        "preexported_feature_artifact_used",
    ):
        if source_policy.get(field) is not False:
            raise ValueError(f"comparison source policy must reject {field}")
    for backend_name in ("bmo", "wakeforge"):
        backend = _require_mapping(comparison.get(backend_name), f"comparison.{backend_name}")
        backend_metrics = _require_mapping(
            backend.get("metrics"), f"comparison.{backend_name}.metrics"
        )
        for field in (
            "attempts",
            "positive_attempts",
            "positive_detections",
            "negative_attempts",
            "false_activations",
            "recall",
            "false_activation_rate",
            "latency_ms_median",
            "latency_ms_p95",
            "latency_ms_max",
            "score_by_category",
        ):
            if field not in backend_metrics:
                raise ValueError(f"missing comparison metric: {backend_name}.{field}")
        if not isinstance(backend_metrics["score_by_category"], dict):
            raise ValueError(f"invalid comparison score distributions: {backend_name}")
        if backend_metrics["attempts"] != (
            backend_metrics["positive_attempts"] + backend_metrics["negative_attempts"]
        ):
            raise ValueError(f"comparison attempt totals do not reconcile: {backend_name}")
        if backend_metrics["positive_detections"] > backend_metrics["positive_attempts"]:
            raise ValueError(f"comparison positive detections exceed attempts: {backend_name}")
        if backend_metrics["false_activations"] > backend_metrics["negative_attempts"]:
            raise ValueError(f"comparison false activations exceed attempts: {backend_name}")
    physical = _require_mapping(payload["physical"], "physical")
    if physical.get("owner_status") != "pending" or physical.get("status") != "pending":
        raise ValueError("v2 physical gate must remain pending before owner acceptance")
    if physical.get("short_natural_use_gate_only_after_software_pass") is not True:
        raise ValueError("v2 physical gate sequencing is missing")
    policy = _require_mapping(physical.get("owner_gate_policy"), "physical.owner_gate_policy")
    if policy.get("positive_wake_activations_min") != 3:
        raise ValueError("v2 owner wake policy must require at least 3 activations")
    if policy.get("positive_wake_activations_max") != 5:
        raise ValueError("v2 owner wake policy must cap activations at 5")
    if policy.get("representative_negative_cases_max") != 5:
        raise ValueError("v2 owner wake policy must keep negative cases bounded")
    if policy.get("no_20_round_owner_calibration") is not True:
        raise ValueError("v2 owner gate must not require 20-round calibration")
    for field in (
        "single_utterance_preroll",
        "right_ctrl_shared_pipeline",
        "smart_turn_natural_pause",
    ):
        if policy.get(field) is not True:
            raise ValueError(f"v2 owner gate policy must require {field}")
    privacy = _require_mapping(payload["privacy"], "privacy")
    if missing := V2_REQUIRED_PRIVACY - privacy.keys():
        raise ValueError(f"missing v2 privacy fields: {sorted(missing)}")
    for field in V2_REQUIRED_PRIVACY - {"credential_in_evidence"}:
        if privacy[field] is not False and field.startswith("raw_audio"):
            raise ValueError(f"raw audio retention field is not false: {field}")
    if privacy["bounded_buffers_cleared"] is not True:
        raise ValueError("bounded buffers must be cleared")
    if privacy["credential_in_evidence"] is not False:
        raise ValueError("credentials must not be in evidence")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def validate_evidence(payload: dict[str, Any]) -> None:
    """Reject incomplete, non-sanitized, or contradictory Phase 10 evidence."""

    schema = payload.get("schema_version")
    if schema == "phase-10-voice-v2-evidence/v1":
        _validate_v2_evidence(payload)
    else:
        _validate_v1_evidence(payload)


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
