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
    "wake_cascade",
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

CASCADE_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "phase",
    "wake_word",
    "synthetic_only",
    "owner_audio_used",
    "raw_audio_retained",
    "temporary_audio_removed",
    "corpus",
    "candidate_stages",
    "verifiers",
    "winner",
    "decision",
    "owner_enrollment_justified",
    "phase_11_boundary",
}
CASCADE_METRICS = {
    "attempts",
    "positive_attempts",
    "positive_detections",
    "final_recall",
    "negative_attempts",
    "false_activations",
    "final_false_activation_rate",
    "false_activations_by_category",
    "verifier_invocations",
    "candidate_to_verification_latency_ms_p50",
    "candidate_to_verification_latency_ms_p95",
    "hard_phonetic_false_accepts",
}
CASCADE_SWEEP_METRICS = {
    "threshold",
    "candidate_recall",
    "candidate_false_activation_rate",
    "candidate_volume",
    "final_recall",
    "final_false_activation_rate",
    "verifier_invocations",
    "candidate_to_verification_latency_ms_p50",
    "candidate_to_verification_latency_ms_p95",
}

WAKE_VERIFIER_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "phase",
    "implementation_commit",
    "wake_word",
    "synthetic_only",
    "owner_audio_used",
    "raw_audio_retained",
    "temporary_audio_removed",
    "corpus",
    "candidate_architectures",
    "decode_contract",
    "models",
    "cuda_runtime",
    "final_held_out",
    "selection",
    "owner_enrollment_justified",
    "phase_11_boundary",
}
WAKE_VERIFIER_METRICS = {
    "attempts",
    "positive_attempts",
    "positive_detections",
    "final_recall",
    "negative_attempts",
    "false_activations",
    "final_false_activation_rate",
    "false_activations_by_category",
    "miss_categories",
    "verifier_invocations",
    "warm_latency_ms_p50",
    "warm_latency_ms_p95",
}
WAKE_VERIFIER_MODELS = {
    "tiny.en": {
        "repository": "Systran/faster-whisper-tiny.en",
        "revision": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
    },
    "base.en": {
        "repository": "Systran/faster-whisper-base.en",
        "revision": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
    },
    "small.en": {
        "repository": "Systran/faster-whisper-small.en",
        "revision": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
    },
}
WAKE_VERIFIER_CATEGORIES = {
    "positive",
    "normal_english",
    "hard_phonetic",
    "arabic",
    "mixed",
    "background_conversation",
    "silence_noise",
    "media_playback",
    "assistant_tts_playback",
    "fan_keyboard_noise",
}

RESELECTION_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "phase",
    "wake_phrase",
    "software_tested_commit",
    "decision",
    "micro_wake_word",
    "open_wake_word",
    "acceptance_policy",
    "owner_physical_gate_authorized",
    "privacy",
    "phase_11_boundary",
}


def _validate_reselection_counts(value: Any, name: str) -> dict[str, Any]:
    metrics = _require_mapping(value, name)
    required = {
        "positive_attempts",
        "positive_detections",
        "negative_attempts",
        "false_activations",
        "recall",
        "far",
    }
    if missing := required - metrics.keys():
        raise ValueError(f"missing wake reselection metrics: {name}: {sorted(missing)}")
    counts = tuple(metrics[field] for field in required if field not in {"recall", "far"})
    if not all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in counts
    ):
        raise ValueError(f"wake reselection counts must be non-negative integers: {name}")
    positive = metrics["positive_attempts"]
    detections = metrics["positive_detections"]
    negative = metrics["negative_attempts"]
    false_activations = metrics["false_activations"]
    if detections > positive or false_activations > negative:
        raise ValueError(f"wake reselection counts exceed denominators: {name}")
    if abs(float(metrics["recall"]) - detections / max(1, positive)) > 0.0001:
        raise ValueError(f"wake reselection recall does not reconcile: {name}")
    if abs(float(metrics["far"]) - false_activations / max(1, negative)) > 0.0001:
        raise ValueError(f"wake reselection FAR does not reconcile: {name}")
    return metrics


def _validate_wake_backend_reselection_evidence(payload: dict[str, Any]) -> None:
    """Validate the comparative Hey Jarvis backend reselection evidence."""

    if missing := RESELECTION_REQUIRED_TOP_LEVEL - payload.keys():
        raise ValueError(f"missing wake backend reselection fields: {sorted(missing)}")
    if (
        payload["schema_version"] != "phase-10-wake-backend-reselection/v1"
        or payload["phase"] != 10
        or payload["wake_phrase"] != "Hey Jarvis"
    ):
        raise ValueError("unsupported wake backend reselection schema")
    commit = payload["software_tested_commit"]
    if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
        raise ValueError("wake backend reselection software_tested_commit must be a full Git SHA")
    if payload["decision"] != "blocked_both_candidates":
        raise ValueError("reselection evidence must record that both candidates are blocked")
    if payload["owner_physical_gate_authorized"] is not False:
        raise ValueError("physical acceptance must remain unauthorized")
    policy = _require_mapping(payload["acceptance_policy"], "acceptance_policy")
    for field, expected in (
        ("minimum_recall", 0.98),
        ("minimum_far", 0.0025),
        ("minimum_continuous_faph", 0.1),
        ("target_recall", 0.99),
        ("target_far", 0.001),
        ("target_continuous_faph", 0.1),
    ):
        if policy.get(field) != expected:
            raise ValueError(f"reselection acceptance policy mismatch: {field}")
    micro = _require_mapping(payload["micro_wake_word"], "micro_wake_word")
    expected_micro = {
        "backend": "official_microwakeword_v2",
        "model_repository": "https://github.com/esphome/micro-wake-word-models",
        "model_revision": "main",
        "model_commit": "05b65922cc433c9df13e98e32a7fe520758c837e",
        "model_git_blob": "0075302434cc72a460ced0b8f6c09c69214e5cf0",
        "artifact_filename": "hey_jarvis.tflite",
        "model_sha256": "21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77",
        "runtime_version": "pymicro-wakeword==2.4.1; pymicro-features==2.0.2",
    }
    for field, expected_identity in expected_micro.items():
        if micro.get(field) != expected_identity:
            raise ValueError(f"microWakeWord identity mismatch: {field}")
    if (
        micro.get("license")
        != "Apache-2.0 collection license; artifact-specific terms not declared"
    ):
        raise ValueError("microWakeWord license status is incomplete")
    micro_held_out = _validate_reselection_counts(micro.get("held_out"), "microWakeWord held-out")
    if (
        micro_held_out["positive_attempts"] != 504
        or micro_held_out["negative_attempts"] != 7268
        or micro_held_out["positive_detections"] != 217
        or micro_held_out["false_activations"] != 262
    ):
        raise ValueError("microWakeWord held-out result does not match the recorded run")
    micro_continuous = _require_mapping(
        micro.get("continuous_negative_stream"), "microWakeWord stream"
    )
    if micro_continuous.get("status") != "not_run_for_rejected_candidate":
        raise ValueError(
            "microWakeWord continuous stream must be marked not run after early rejection"
        )
    openwake = _require_mapping(payload["open_wake_word"], "open_wake_word")
    expected_openwake = {
        "model_repository": "https://github.com/dscripka/openWakeWord",
        "model_revision": "v0.5.1",
        "model_commit": "1eec2158c5c54150ac5f4c15065adacb1003b1e7",
        "artifact_filename": "hey_jarvis_v0.1.onnx",
        "model_sha256": "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
    }
    for field, expected_identity in expected_openwake.items():
        if openwake.get(field) != expected_identity:
            raise ValueError(f"openWakeWord identity mismatch: {field}")
    cascade = _validate_reselection_counts(openwake.get("cascade_held_out"), "openWakeWord cascade")
    if (
        cascade["positive_attempts"] != 504
        or cascade["negative_attempts"] != 7268
        or cascade["positive_detections"] != 489
        or cascade["false_activations"] != 75
    ):
        raise ValueError("openWakeWord cascade result does not match the recorded run")
    raw = _validate_reselection_counts(openwake.get("raw_no_vad_held_out"), "openWakeWord raw")
    if raw["positive_detections"] != 503 or raw["false_activations"] != 560:
        raise ValueError("openWakeWord raw result does not match the recorded run")
    bounded_vad = _validate_reselection_counts(
        openwake.get("bounded_vad_held_out"), "openWakeWord bounded VAD"
    )
    if bounded_vad["positive_attempts"] != 48 or bounded_vad["negative_attempts"] != 516:
        raise ValueError("openWakeWord bounded VAD corpus does not match the recorded run")
    stream = _require_mapping(openwake.get("continuous_negative_stream"), "openWakeWord stream")
    if (
        stream.get("status") != "measured"
        or stream.get("audio_hours") != 5.0
        or stream.get("false_wake_events") != 1
        or stream.get("false_activations_per_hour") != 0.2
        or stream.get("acceptance_passed") is not False
    ):
        raise ValueError("openWakeWord continuous stream result is incomplete or inconsistent")
    privacy = _require_mapping(payload["privacy"], "privacy")
    for field in (
        "raw_audio_retained",
        "raw_audio_logged",
        "owner_audio_used",
        "credentials_recorded",
    ):
        if privacy.get(field) is not False:
            raise ValueError(f"reselection privacy field must be false: {field}")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _validate_wake_verifier_metrics(value: Any, name: str) -> dict[str, Any]:
    metrics = _require_mapping(value, name)
    if missing := WAKE_VERIFIER_METRICS - metrics.keys():
        raise ValueError(f"missing wake verifier metrics: {name}: {sorted(missing)}")
    positive = metrics["positive_attempts"]
    negative = metrics["negative_attempts"]
    attempts = metrics["attempts"]
    detections = metrics["positive_detections"]
    false_activations = metrics["false_activations"]
    if not all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0
        for item in (positive, negative, attempts, detections, false_activations)
    ):
        raise ValueError(f"wake verifier counts must be non-negative integers: {name}")
    if attempts != positive + negative or detections > positive or false_activations > negative:
        raise ValueError(f"wake verifier counts do not reconcile: {name}")
    expected_recall = detections / positive if positive else 0.0
    expected_far = false_activations / negative if negative else 0.0
    if abs(float(metrics["final_recall"]) - expected_recall) > 0.0001:
        raise ValueError(f"wake verifier recall does not reconcile: {name}")
    if abs(float(metrics["final_false_activation_rate"]) - expected_far) > 0.0001:
        raise ValueError(f"wake verifier FAR does not reconcile: {name}")
    if not isinstance(metrics["false_activations_by_category"], dict):
        raise ValueError(f"wake verifier category metrics must be an object: {name}")
    if not isinstance(metrics["miss_categories"], dict):
        raise ValueError(f"wake verifier miss categories must be an object: {name}")
    for field in ("warm_latency_ms_p50", "warm_latency_ms_p95"):
        if not isinstance(metrics[field], (int, float)) or metrics[field] < 0:
            raise ValueError(f"wake verifier latency is invalid: {name}.{field}")
    return metrics


def _validate_wake_verifier_optimization_evidence(payload: dict[str, Any]) -> None:
    missing = WAKE_VERIFIER_REQUIRED_TOP_LEVEL - payload.keys()
    if missing:
        raise ValueError(f"missing wake verifier top-level fields: {sorted(missing)}")
    if (
        payload["schema_version"] != "phase-10-wake-verifier-optimization/v1"
        or payload["phase"] != 10
        or payload["wake_word"] != "Jarvis"
    ):
        raise ValueError("unsupported wake verifier optimization evidence schema")
    if not isinstance(payload["implementation_commit"], str) or not SHA_PATTERN.fullmatch(
        payload["implementation_commit"]
    ):
        raise ValueError("wake verifier implementation_commit must be a full lowercase Git SHA")
    for field in ("synthetic_only", "temporary_audio_removed"):
        if payload[field] is not True:
            raise ValueError(f"wake verifier evidence must set {field}=true")
    for field in ("owner_audio_used", "raw_audio_retained", "owner_enrollment_justified"):
        if payload[field] is not False:
            raise ValueError(f"wake verifier evidence must set {field}=false")
    corpus = _require_mapping(payload["corpus"], "wake verifier corpus")
    categories = corpus.get("categories")
    if not isinstance(categories, list) or not WAKE_VERIFIER_CATEGORIES.issubset(categories):
        raise ValueError("wake verifier corpus is missing required negative categories")
    final_corpus = _require_mapping(corpus.get("final_held_out"), "wake verifier final corpus")
    if final_corpus.get("negative_attempts", 0) < 1000:
        raise ValueError("wake verifier final corpus must contain at least 1000 negatives")
    if final_corpus.get("positive_attempts", 0) < 100:
        raise ValueError("wake verifier final corpus must contain at least 100 positives")
    architectures = _require_mapping(
        payload["candidate_architectures"], "wake verifier candidate architectures"
    )
    if set(architectures) != {"vad_whisper", "bmo_mfcc_dtw", "wakeforge"}:
        raise ValueError("wake verifier candidate architecture set is incomplete")
    decode = _require_mapping(payload["decode_contract"], "wake verifier decode contract")
    expected_decode = {
        "language": "en",
        "task": "transcribe",
        "condition_on_previous_text": False,
        "without_timestamps": True,
        "temperature": 0.0,
        "prefix_forcing": False,
    }
    for field, expected in expected_decode.items():
        if decode.get(field) != expected:
            raise ValueError(f"wake verifier decode contract mismatch: {field}")
    if decode.get("hotword_values") != [None, "Jarvis"]:
        raise ValueError("wake verifier hotword contract is invalid")
    if set(decode.get("beam_sizes", ())) != {1, 3, 5}:
        raise ValueError("wake verifier beam contract must cover 1, 3, and 5")
    if not decode.get("audio_conditions"):
        raise ValueError("wake verifier audio conditioning results are missing")
    models = _require_mapping(payload["models"], "wake verifier models")
    if set(models) != set(WAKE_VERIFIER_MODELS):
        raise ValueError("wake verifier model set must be tiny.en, base.en, and small.en")
    for name, expected in WAKE_VERIFIER_MODELS.items():
        model = _require_mapping(models[name], f"wake verifier model {name}")
        artifact = _require_mapping(model.get("artifact"), f"wake verifier artifact {name}")
        if artifact.get("repository") != expected["repository"]:
            raise ValueError(f"wake verifier repository is not pinned: {name}")
        if artifact.get("revision") != expected["revision"]:
            raise ValueError(f"wake verifier revision is not pinned: {name}")
        if artifact.get("license") != "MIT":
            raise ValueError(f"wake verifier license is not approved: {name}")
        files = _require_mapping(artifact.get("files"), f"wake verifier files {name}")
        if not files:
            raise ValueError(f"wake verifier file manifest is empty: {name}")
        for relative, record in files.items():
            if Path(relative).is_absolute():
                raise ValueError(f"wake verifier manifest contains an absolute path: {name}")
            file_record = _require_mapping(record, f"wake verifier file {name}/{relative}")
            if not isinstance(file_record.get("bytes"), int) or file_record["bytes"] <= 0:
                raise ValueError(f"wake verifier file size is invalid: {name}/{relative}")
            if not isinstance(file_record.get("sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", file_record["sha256"]
            ):
                raise ValueError(f"wake verifier file digest is invalid: {name}/{relative}")
        grid_best = _require_mapping(model.get("grid_best"), f"wake verifier grid {name}")
        _validate_wake_verifier_metrics(grid_best.get("metrics"), f"wake verifier grid {name}")
        if model.get("device") != "cuda" or model.get("compute_type") != "float16":
            raise ValueError(f"wake verifier model was not GPU-tested: {name}")
        for field in ("gpu_vram_bytes", "gpu_temperature_c", "load_ms"):
            if not isinstance(model.get(field), (int, float)) or model[field] < 0:
                raise ValueError(f"wake verifier resource metric is invalid: {name}.{field}")
    final = _require_mapping(payload["final_held_out"], "wake verifier final held-out result")
    if final.get("model") != "base.en":
        raise ValueError("wake verifier final held-out model must be base.en")
    _validate_wake_verifier_metrics(final.get("metrics"), "wake verifier final held-out metrics")
    selection = _require_mapping(payload["selection"], "wake verifier selection")
    if (
        selection.get("required_recall") != 0.95
        or selection.get("max_false_activation_rate") != 0.005
    ):
        raise ValueError("wake verifier acceptance thresholds are invalid")
    if selection.get("decision") not in {"blocked_software_operating_point", "selected"}:
        raise ValueError("wake verifier decision is invalid")
    best = _require_mapping(selection.get("best_observed"), "wake verifier best observed")
    _validate_wake_verifier_metrics(best.get("metrics"), "wake verifier best observed metrics")
    runtime = _require_mapping(payload["cuda_runtime"], "wake verifier CUDA runtime")
    if runtime.get("device") != "cuda" or runtime.get("compute_type") != "float16":
        raise ValueError("wake verifier CUDA runtime was not GPU-tested")
    if runtime.get("load_pass") is not True or runtime.get("one_heavy_model") is not True:
        raise ValueError("wake verifier CUDA runtime gate is incomplete")
    dlls = runtime.get("dlls")
    if not isinstance(dlls, list) or {item.get("name") for item in dlls} != {
        "cudart64_12.dll",
        "cublas64_12.dll",
        "cudnn64_9.dll",
    }:
        raise ValueError("wake verifier CUDA runtime DLL manifest is incomplete")
    for item in dlls:
        record = _require_mapping(item, "wake verifier CUDA DLL")
        if not isinstance(record.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["sha256"]
        ):
            raise ValueError("wake verifier CUDA DLL digest is invalid")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


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
    for field in V2_REQUIRED_SOFTWARE - {
        "synthetic_benchmark",
        "wake_backend_comparison",
        "wake_cascade",
    }:
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
    cascade = _require_mapping(software.get("wake_cascade"), "wake_cascade")
    if cascade.get("schema_version") != "phase-10-wake-cascade/v1":
        raise ValueError("invalid wake cascade schema")
    if cascade.get("evidence_file") != "PHASE_10_WAKE_CASCADE.json":
        raise ValueError("wake cascade evidence file is not canonical")
    cascade_commit = cascade.get("benchmark_script_commit")
    if not isinstance(cascade_commit, str) or not SHA_PATTERN.fullmatch(cascade_commit):
        raise ValueError("wake cascade benchmark commit is not pinned")
    if cascade.get("winner") != "none":
        raise ValueError("cascade winner must remain none until its operating point passes")
    if cascade.get("decision") != "blocked_software_operating_point":
        raise ValueError("cascade decision must remain blocked")
    if cascade.get("owner_enrollment_justified") is not False:
        raise ValueError("cascade summary must not authorize owner enrollment")
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


def _validate_cascade_evidence(payload: dict[str, Any]) -> None:
    """Require a complete scalar held-out two-stage cascade evaluation."""

    if missing := CASCADE_REQUIRED_TOP_LEVEL - payload.keys():
        raise ValueError(f"missing cascade fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-wake-cascade/v1" or payload["phase"] != 10:
        raise ValueError("unsupported Phase 10 wake cascade schema")
    if payload["wake_word"] != "Jarvis":
        raise ValueError("cascade must use exact Jarvis")
    for field in (
        "synthetic_only",
        "owner_audio_used",
        "raw_audio_retained",
        "temporary_audio_removed",
    ):
        if not isinstance(payload[field], bool):
            raise ValueError(f"cascade field must be boolean: {field}")
    if payload["synthetic_only"] is not True or payload["owner_audio_used"] is not False:
        raise ValueError("cascade must be synthetic-only and owner-audio-free")
    if payload["raw_audio_retained"] is not False or payload["temporary_audio_removed"] is not True:
        raise ValueError("cascade audio must be temporary and non-retaining")
    corpus = _require_mapping(payload["corpus"], "cascade.corpus")
    for field in ("attempts", "positive_attempts", "negative_attempts", "categories"):
        if field not in corpus:
            raise ValueError(f"missing cascade corpus field: {field}")
    if corpus["attempts"] != corpus["positive_attempts"] + corpus["negative_attempts"]:
        raise ValueError("cascade corpus totals do not reconcile")
    if corpus.get("held_out_for_all_experiments") is not True:
        raise ValueError("cascade corpus must be held out for all experiments")
    required_categories = {
        "positive",
        "normal_english",
        "hard_phonetic",
        "arabic",
        "mixed",
        "background_conversation",
        "silence_noise",
    }
    if not required_categories.issubset(set(corpus["categories"])):
        raise ValueError("cascade corpus is missing required negative categories")
    candidates = _require_mapping(payload["candidate_stages"], "cascade.candidate_stages")
    for name, direction in (("bmo_mfcc_dtw", "lower_is_better"), ("wakeforge", "higher_is_better")):
        candidate = _require_mapping(candidates.get(name), f"cascade.candidate_stages.{name}")
        if candidate.get("score_direction") != direction:
            raise ValueError(f"invalid cascade score direction: {name}")
        thresholds = candidate.get("thresholds")
        if not isinstance(thresholds, list) or len(thresholds) < 5:
            raise ValueError(f"cascade threshold sweep is too small: {name}")
    wakeforge = candidates["wakeforge"]
    if wakeforge.get("revision") != "1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7":
        raise ValueError("cascade WakeForge revision is not audited")
    for field in ("classifier_sha256", "feature_extractor_sha256"):
        if not isinstance(wakeforge.get(field), str) or not re.fullmatch(
            r"[0-9a-f]{64}", wakeforge[field]
        ):
            raise ValueError(f"invalid WakeForge artifact digest: {field}")
    verifiers = _require_mapping(payload["verifiers"], "cascade.verifiers")
    if not verifiers:
        raise ValueError("cascade requires at least one Whisper verifier")
    for name, verifier in verifiers.items():
        model = _require_mapping(verifier.get("model"), f"cascade.verifiers.{name}.model")
        if model.get("license") != "MIT" or not str(model.get("repository", "")).startswith(
            "Systran/"
        ):
            raise ValueError(f"verifier model is not license-audited: {name}")
        if not isinstance(model.get("revision"), str) or not SHA_PATTERN.fullmatch(
            model["revision"]
        ):
            raise ValueError(f"verifier revision is not pinned: {name}")
        files = _require_mapping(model.get("files"), f"cascade.verifiers.{name}.model.files")
        if not files:
            raise ValueError(f"verifier file manifest is empty: {name}")
        for relative, record in files.items():
            if Path(relative).is_absolute():
                raise ValueError(f"verifier manifest contains an absolute path: {name}")
            file_record = _require_mapping(
                record, f"cascade.verifiers.{name}.model.files.{relative}"
            )
            if not isinstance(file_record.get("sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", file_record["sha256"]
            ):
                raise ValueError(f"verifier file digest is invalid: {name}/{relative}")
        cascades = _require_mapping(verifier.get("cascades"), f"cascade.verifiers.{name}.cascades")
        for candidate_name in ("bmo_mfcc_dtw", "wakeforge"):
            result = _require_mapping(
                cascades.get(candidate_name), f"cascade.verifiers.{name}.{candidate_name}"
            )
            sweep = result.get("threshold_sweep")
            if not isinstance(sweep, list) or not sweep:
                raise ValueError(f"missing cascade threshold results: {name}/{candidate_name}")
            for row in sweep:
                if missing := CASCADE_SWEEP_METRICS - row.keys():
                    raise ValueError(
                        f"missing cascade metric: {name}/{candidate_name}: {sorted(missing)}"
                    )
            best = _require_mapping(
                result.get("best_observed"),
                f"cascade.verifiers.{name}.{candidate_name}.best_observed",
            )
            if missing := CASCADE_METRICS - best.keys():
                raise ValueError(
                    f"missing best cascade metric: {name}/{candidate_name}: {sorted(missing)}"
                )
        control = _require_mapping(
            verifier.get("vad_whisper_control"), f"cascade.verifiers.{name}.vad_whisper_control"
        )
        if missing := CASCADE_METRICS - control.keys():
            raise ValueError(f"missing VAD control metric: {name}: {sorted(missing)}")
    if payload["winner"] not in {"none", "bmo_mfcc_dtw", "wakeforge", "vad_whisper"}:
        raise ValueError("invalid cascade winner")
    if payload["winner"] == "none" and payload["decision"] != "blocked_software_operating_point":
        raise ValueError("blocked cascade must record its blocked decision")
    if payload["winner"] != "none" and payload["decision"] == "blocked_software_operating_point":
        raise ValueError("blocked cascade cannot record a selected winner")
    if payload["owner_enrollment_justified"] is not False:
        raise ValueError("cascade must not authorize owner enrollment")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def _validate_stateful_wake_isolation_evidence(payload: dict[str, Any]) -> None:
    required_top = {
        "schema_version",
        "phase",
        "architecture_version",
        "wake_word",
        "implementation_commit",
        "synthetic_only",
        "owner_audio_used",
        "raw_audio_retained",
        "temporary_audio_removed",
        "acoustic_verifier",
        "stateful_production_gate",
        "decision",
        "owner_physical_gate_ready",
        "owner_enrollment_required",
        "phase_11_boundary",
        "measurement_mode",
        "production_capture_equivalent",
    }
    if missing := required_top - payload.keys():
        raise ValueError(f"missing stateful wake isolation top-level fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-stateful-wake-isolation/v1" or payload["phase"] != 10:
        raise ValueError("unsupported stateful wake isolation schema")
    if payload["wake_word"] != "Jarvis":
        raise ValueError("stateful wake isolation must use exact Jarvis")
    if not isinstance(payload["implementation_commit"], str) or not SHA_PATTERN.fullmatch(
        payload["implementation_commit"]
    ):
        raise ValueError("implementation_commit must be a full lowercase Git SHA")
    for field in ("synthetic_only", "temporary_audio_removed"):
        if payload[field] is not True:
            raise ValueError(f"stateful wake isolation evidence must set {field}=true")
    for field in ("owner_audio_used", "raw_audio_retained", "owner_enrollment_required"):
        if payload[field] is not False:
            raise ValueError(f"stateful wake isolation evidence must set {field}=false")

    if payload["measurement_mode"] == "whole_utterance_frame_pre_fix":
        if payload["production_capture_equivalent"] is not False:
            raise ValueError(
                "historical whole-utterance evidence must not claim capture equivalence"
            )
        if payload["decision"] != "historical_non_streaming_measurement":
            raise ValueError("historical wake evidence decision is invalid")
        if payload["owner_physical_gate_ready"] is not False:
            raise ValueError("historical wake evidence cannot authorize physical acceptance")
        _walk_forbidden(payload)
        return
    if payload["measurement_mode"] != "stateful_streaming_pre_fix":
        raise ValueError("stateful wake measurement mode is invalid")
    if payload["production_capture_equivalent"] is not True:
        raise ValueError("stateful streaming evidence must claim capture equivalence")
    if payload["owner_physical_gate_ready"] is not True:
        raise ValueError("stateful streaming evidence must set owner_physical_gate_ready=true")

    verifier = _require_mapping(payload["acoustic_verifier"], "acoustic_verifier")
    if verifier.get("model") != "base.en":
        raise ValueError("acoustic verifier model must be base.en")
    if verifier.get("revision") != "3d3d5dee26484f91867d81cb899cfcf72b96be6c":
        raise ValueError("acoustic verifier revision is not pinned")
    if verifier.get("license") != "MIT":
        raise ValueError("acoustic verifier license must be MIT")
    if verifier.get("device") != "cuda" or verifier.get("compute_type") != "float16":
        raise ValueError("acoustic verifier must be CUDA float16")

    gate = _require_mapping(payload["stateful_production_gate"], "stateful_production_gate")
    positives = _require_mapping(gate.get("sleeping_positives"), "sleeping_positives")
    if positives.get("attempts", 0) < 100 or positives.get("recall", 0.0) < 0.95:
        raise ValueError("sleeping positives must meet >=95% recall")

    negatives = _require_mapping(
        gate.get("sleeping_external_negatives"), "sleeping_external_negatives"
    )
    if negatives.get("attempts", 0) < 900 or negatives.get("false_activation_rate", 1.0) > 0.005:
        raise ValueError("sleeping external negatives must meet <=0.5% FAR")

    speaking = _require_mapping(
        gate.get("speaking_assistant_playback"), "speaking_assistant_playback"
    )
    if (
        speaking.get("attempts", 0) < 100
        or speaking.get("verifier_invocations") != 0
        or speaking.get("wake_transitions") != 0
        or speaking.get("core_submissions") != 0
    ):
        raise ValueError(
            "speaking assistant playback must produce zero wake invocations or transitions"
        )

    follow_up = _require_mapping(
        gate.get("follow_up_assistant_playback"), "follow_up_assistant_playback"
    )
    if (
        follow_up.get("attempts", 0) < 100
        or follow_up.get("verifier_invocations") != 0
        or follow_up.get("wake_transitions") != 0
        or follow_up.get("owner_follow_up_turns_passed", 0) < 100
    ):
        raise ValueError(
            "follow-up assistant playback must produce zero wake transitions and allow owner turns"
        )

    stale_tail = _require_mapping(gate.get("stale_tail_simulation"), "stale_tail_simulation")
    if stale_tail.get("tail_false_activations") != 0:
        raise ValueError("stale tail simulation must have zero false activations")

    imm_sleep = _require_mapping(
        gate.get("immediate_sleep_simulation"), "immediate_sleep_simulation"
    )
    if imm_sleep.get("tail_false_activations") != 0:
        raise ValueError("immediate sleep simulation must have zero false activations")

    barge_in = _require_mapping(gate.get("barge_in_simulation"), "barge_in_simulation")
    if barge_in.get("interruption_passed", 0) <= 0:
        raise ValueError("barge-in simulation must pass")

    preroll = _require_mapping(
        gate.get("single_utterance_preroll_simulation"), "single_utterance_preroll_simulation"
    )
    if preroll.get("command_preserved_passed", 0) <= 0:
        raise ValueError("single-utterance pre-roll simulation must pass")

    if gate.get("production_reachable_false_activation_rate", 1.0) > 0.005:
        raise ValueError("production reachable FAR must be <=0.5%")
    if gate.get("production_recall", 0.0) < 0.95:
        raise ValueError("production recall must be >=95%")

    if payload["decision"] != "state_aware_wake_isolation_passed":
        raise ValueError("stateful wake isolation decision is invalid")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def _validate_streaming_wake_path_evidence(payload: dict[str, Any]) -> None:
    """Validate the realistic 80 ms streaming wake software gate."""

    required_top = {
        "schema_version",
        "phase",
        "architecture_version",
        "wake_word",
        "implementation_commit",
        "synthetic_only",
        "owner_audio_used",
        "raw_audio_retained",
        "temporary_audio_removed",
        "capture_stream",
        "streaming_timing_sweep",
        "acoustic_verifier",
        "stateful_production_gate",
        "decision",
        "owner_physical_gate_ready",
        "owner_enrollment_required",
        "phase_11_boundary",
    }
    if missing := required_top - payload.keys():
        raise ValueError(f"missing streaming wake top-level fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-streaming-wake-path/v1" or payload["phase"] != 10:
        raise ValueError("unsupported streaming wake path schema")
    if payload["architecture_version"] != "2" or payload["wake_word"] != "Jarvis":
        raise ValueError("streaming wake path must use Phase 10 v2 exact Jarvis")
    if not isinstance(payload["implementation_commit"], str) or not SHA_PATTERN.fullmatch(
        payload["implementation_commit"]
    ):
        raise ValueError("streaming implementation_commit must be a full lowercase Git SHA")
    for field in ("synthetic_only", "temporary_audio_removed"):
        if payload[field] is not True:
            raise ValueError(f"streaming wake evidence must set {field}=true")
    for field in ("owner_audio_used", "raw_audio_retained", "owner_enrollment_required"):
        if payload[field] is not False:
            raise ValueError(f"streaming wake evidence must set {field}=false")
    if payload["owner_physical_gate_ready"] not in {True, False}:
        raise ValueError("streaming wake physical readiness must be boolean")

    capture = _require_mapping(payload["capture_stream"], "capture_stream")
    if (
        capture.get("frame_duration_ms") != 80
        or capture.get("frame_samples") != 1280
        or capture.get("sample_rate_hz") != 16_000
        or capture.get("streaming_path") != "JarvisVoicePipeline.on_capture_frame"
        or capture.get("production_capture_equivalent") is not True
        or capture.get("whole_utterance_frame_regression") is not True
    ):
        raise ValueError("streaming capture contract is incomplete or not production-equivalent")

    verifier = _require_mapping(payload["acoustic_verifier"], "acoustic_verifier")
    if (
        verifier.get("model") != "base.en"
        or verifier.get("revision") != "3d3d5dee26484f91867d81cb899cfcf72b96be6c"
        or verifier.get("license") != "MIT"
        or verifier.get("device") != "cuda"
        or verifier.get("compute_type") != "float16"
    ):
        raise ValueError("streaming acoustic verifier identity is not accepted")

    sweep = _require_mapping(payload["streaming_timing_sweep"], "streaming_timing_sweep")
    if sweep.get("verifier_model") != "base.en":
        raise ValueError("streaming timing sweep must use base.en")
    if sweep.get("initial_verification_windows_ms") != [320, 400, 480, 560, 640, 800]:
        raise ValueError("streaming timing sweep windows are incomplete")
    if sweep.get("retry_cadence_ms") != [160, 320]:
        raise ValueError("streaming timing sweep retry cadences are incomplete")
    if sweep.get("maximum_candidate_seconds") != 1.8 or sweep.get("maximum_verifier_attempts") != 4:
        raise ValueError("streaming timing bounds are not the accepted bounded profile")
    results = sweep.get("results")
    if not isinstance(results, list) or len(results) != 12:
        raise ValueError("streaming timing sweep must contain all 12 bounded configurations")
    valid_rows: set[tuple[int, int]] = set()
    for row in results:
        item = _require_mapping(row, "streaming timing result")
        required = {
            "initial_verification_window_ms",
            "retry_cadence_ms",
            "positive_attempts",
            "positive_detections",
            "recall",
            "negative_attempts",
            "false_activations",
            "false_activation_rate",
            "wake_latency_ms_p50",
            "wake_latency_ms_p95",
        }
        if missing := required - item.keys():
            raise ValueError(f"streaming timing result is incomplete: {sorted(missing)}")
        window = item["initial_verification_window_ms"]
        retry = item["retry_cadence_ms"]
        if (window, retry) in valid_rows or window not in {320, 400, 480, 560, 640, 800}:
            raise ValueError("streaming timing result configuration is invalid")
        if retry not in {160, 320}:
            raise ValueError("streaming timing retry configuration is invalid")
        valid_rows.add((window, retry))
        if item["positive_attempts"] < 36 or item["negative_attempts"] < 258:
            raise ValueError("streaming timing result corpus is too small")
        if not 0 <= item["positive_detections"] <= item["positive_attempts"]:
            raise ValueError("streaming timing positive counts are invalid")
        if not 0 <= item["false_activations"] <= item["negative_attempts"]:
            raise ValueError("streaming timing negative counts are invalid")
        if item["recall"] != round(item["positive_detections"] / item["positive_attempts"], 4):
            raise ValueError("streaming timing recall does not reconcile")
        if item["false_activation_rate"] != round(
            item["false_activations"] / item["negative_attempts"], 4
        ):
            raise ValueError("streaming timing FAR does not reconcile")
        for field in ("wake_latency_ms_p50", "wake_latency_ms_p95"):
            if not isinstance(item[field], (int, float)) or item[field] < 0:
                raise ValueError("streaming timing latency is invalid")
    if valid_rows != {
        (window, retry) for window in (320, 400, 480, 560, 640, 800) for retry in (160, 320)
    }:
        raise ValueError("streaming timing sweep configurations are incomplete")
    selected = (sweep.get("selected_initial_window_ms"), sweep.get("selected_retry_cadence_ms"))
    if selected not in valid_rows:
        raise ValueError("streaming selected timing configuration is invalid")
    selected_rows = [
        row
        for row in results
        if (row["initial_verification_window_ms"], row["retry_cadence_ms"]) == selected
    ]
    selected_row = selected_rows[0]
    selected_operating = bool(sweep.get("selected_operating_point"))
    selected_meets_gate = (
        selected_row["recall"] >= 0.95 and selected_row["false_activation_rate"] <= 0.005
    )
    if selected_operating != selected_meets_gate:
        raise ValueError("streaming selected operating-point claim does not reconcile")

    gate = _require_mapping(payload["stateful_production_gate"], "stateful_production_gate")
    positives = _require_mapping(gate.get("sleeping_positives"), "sleeping_positives")
    if (
        positives.get("attempts", 0) < 100
        or positives.get("detections", -1) < 0
        or positives.get("detections", 0) > positives.get("attempts", 0)
        or positives.get("recall")
        != round(positives.get("detections", 0) / positives.get("attempts", 1), 4)
        or positives.get("recall", 0.0) < 0.95
    ):
        raise ValueError("streaming sleeping positives must reconcile at >=95% recall")
    negatives = _require_mapping(
        gate.get("sleeping_external_negatives"), "sleeping_external_negatives"
    )
    if (
        negatives.get("attempts", 0) < 900
        or negatives.get("false_activations", -1) < 0
        or negatives.get("false_activations", 0) > negatives.get("attempts", 0)
        or negatives.get("false_activation_rate")
        != round(negatives.get("false_activations", 0) / negatives.get("attempts", 1), 4)
        or negatives.get("false_activation_rate", 1.0) > 0.005
    ):
        raise ValueError("streaming sleeping negatives must reconcile at <=0.5% FAR")
    speaking = _require_mapping(
        gate.get("speaking_assistant_playback"), "speaking_assistant_playback"
    )
    if any(
        speaking.get(field) != 0
        for field in ("verifier_invocations", "wake_transitions", "core_submissions")
    ):
        raise ValueError("streaming assistant playback isolation must remain zero")
    follow_up = _require_mapping(
        gate.get("follow_up_assistant_playback"), "follow_up_assistant_playback"
    )
    if any(follow_up.get(field) != 0 for field in ("verifier_invocations", "wake_transitions")):
        raise ValueError("streaming follow-up playback isolation must remain zero")
    for name in ("stale_tail_simulation", "immediate_sleep_simulation"):
        item = _require_mapping(gate.get(name), name)
        if item.get("tail_false_activations") != 0 or item.get("subsequent_wake_passed", 0) <= 0:
            raise ValueError(f"{name} must prove zero tail activations and recovery")
    if (
        _require_mapping(gate.get("barge_in_simulation"), "barge_in_simulation").get(
            "interruption_passed", 0
        )
        <= 0
    ):
        raise ValueError("streaming barge-in simulation must pass")
    if (
        _require_mapping(
            gate.get("single_utterance_preroll_simulation"), "single_utterance_preroll_simulation"
        ).get("command_preserved_passed", 0)
        <= 0
    ):
        raise ValueError("streaming single-utterance pre-roll must pass")
    if gate.get("production_reachable_false_activation_rate", 1.0) > 0.005:
        raise ValueError("streaming production FAR must be <=0.5%")
    if gate.get("production_recall", 0.0) < 0.95:
        raise ValueError("streaming production recall must be >=95%")

    decision = payload["decision"]
    if decision == "streaming_wake_path_passed":
        if not selected_operating or payload["owner_physical_gate_ready"] is not True:
            raise ValueError(
                "streaming pass requires a selected operating point and owner readiness"
            )
    elif decision == "blocked_streaming_operating_point":
        if payload["owner_physical_gate_ready"] is not False:
            raise ValueError("blocked streaming evidence cannot authorize owner acceptance")
    else:
        raise ValueError("streaming wake path decision is invalid")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def _validate_final_hey_jarvis_evidence(payload: dict[str, Any]) -> None:
    """Validate the final one-backend Hey Jarvis architecture evidence."""

    required = {
        "schema_version",
        "phase",
        "wake_phrase",
        "backend",
        "model",
        "research",
        "software_tested_commit",
        "calibration_split",
        "held_out_split",
        "candidate_policy_sweep",
        "continuous_negative_stream",
        "software_gate",
        "production_gate_passed",
        "physical_gate_status",
        "cleanup",
        "privacy",
        "phase_11_boundary",
    }
    if missing := required - payload.keys():
        raise ValueError(f"missing final Hey Jarvis evidence fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-hey-jarvis-final/v1" or payload["phase"] != 10:
        raise ValueError("unsupported final Hey Jarvis evidence schema")
    if payload["wake_phrase"] != "Hey Jarvis":
        raise ValueError("final Hey Jarvis evidence must use the canonical phrase")
    if payload["backend"] != "openwakeword_candidate_whisper_verifier":
        raise ValueError("final evidence must select exactly one production cascade")
    commit = payload["software_tested_commit"]
    if not isinstance(commit, str) or not SHA_PATTERN.fullmatch(commit):
        raise ValueError("final evidence software_tested_commit must be a full Git SHA")
    model = _require_mapping(payload["model"], "final Hey Jarvis model")
    expected_model = {
        "repository": "https://github.com/dscripka/openWakeWord",
        "revision": "v0.5.1",
        "commit": "1eec2158c5c54150ac5f4c15065adacb1003b1e7",
        "filename": "hey_jarvis_v0.1.onnx",
        "sha256": "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
        "engine_license": "Apache-2.0",
        "pretrained_model_license": "CC-BY-NC-SA-4.0",
    }
    for field, expected in expected_model.items():
        if model.get(field) != expected:
            raise ValueError(f"final Hey Jarvis model identity mismatch: {field}")
    research = _require_mapping(payload["research"], "final Hey Jarvis research")
    for field in (
        "openwakeword_inspected",
        "micro_wake_word_inspected",
        "openvoiceos_listener_inspected",
        "rhasspy_temporal_patterns_inspected",
        "windows_audio_patterns_inspected",
    ):
        if research.get(field) is not True:
            raise ValueError(f"required wake research is missing: {field}")
    calibration = _require_mapping(payload["calibration_split"], "final calibration split")
    held_out = _require_mapping(payload["held_out_split"], "final held-out split")
    for name, split in (("calibration", calibration), ("held_out", held_out)):
        for field in ("attempts", "positive_attempts", "negative_attempts"):
            if not isinstance(split.get(field), int) or split[field] < 0:
                raise ValueError(f"final {name} count is invalid: {field}")
        if split["attempts"] != split["positive_attempts"] + split["negative_attempts"]:
            raise ValueError(f"final {name} counts do not reconcile")
    if held_out["positive_attempts"] < 100 or held_out["negative_attempts"] < 1000:
        raise ValueError("final held-out corpus is too small")
    sweep = payload["candidate_policy_sweep"]
    if not isinstance(sweep, list) or not sweep:
        raise ValueError("final candidate policy sweep is missing")
    for row in sweep:
        item = _require_mapping(row, "final candidate policy row")
        required_metrics = {
            "threshold",
            "temporal_policy",
            "window_frames",
            "required_hits_in_window",
            "positive_attempts",
            "positive_detections",
            "negative_attempts",
            "false_activations",
            "recall",
            "far",
        }
        if missing := required_metrics - item.keys():
            raise ValueError(f"final candidate policy row is incomplete: {sorted(missing)}")
        if item["positive_detections"] > item["positive_attempts"]:
            raise ValueError("final candidate policy positive counts do not reconcile")
        if item["false_activations"] > item["negative_attempts"]:
            raise ValueError("final candidate policy negative counts do not reconcile")
    stream = _require_mapping(
        payload["continuous_negative_stream"], "final continuous negative stream"
    )
    if stream.get("status") not in {"pass", "measured", "not_run"}:
        raise ValueError("final continuous stream status is invalid")
    if stream.get("status") in {"pass", "measured"}:
        if stream.get("audio_hours", 0) < 5.0:
            raise ValueError("final continuous stream must cover at least five hours")
        if stream.get("status") == "pass" and stream.get("false_activations_per_hour", 1.0) > 0.1:
            raise ValueError("final continuous stream exceeds the FAPH limit")
    gate = _require_mapping(payload["software_gate"], "final software gate")
    if gate.get("minimum_recall") != 0.98 or gate.get("target_recall") != 0.99:
        raise ValueError("final software recall gate is invalid")
    if gate.get("minimum_far") != 0.0025 or gate.get("target_far") != 0.001:
        raise ValueError("final software FAR gate is invalid")
    if payload["production_gate_passed"] is True:
        if stream.get("status") != "pass":
            raise ValueError("production gate cannot pass without continuous evidence")
        if payload["physical_gate_status"] != "ready_after_software_gate":
            raise ValueError("physical gate readiness does not reconcile")
    elif payload["physical_gate_status"] != "blocked_software_gate":
        raise ValueError("blocked software gate must block physical acceptance")
    cleanup = _require_mapping(payload["cleanup"], "final cleanup")
    if cleanup.get("historical_evidence_preserved") is not True:
        raise ValueError("historical wake evidence must be preserved")
    if cleanup.get("obsolete_runnable_paths_removed") is not True:
        raise ValueError("obsolete runnable wake paths must be removed")
    privacy = _require_mapping(payload["privacy"], "final privacy")
    for field in ("raw_audio_retained", "raw_audio_logged", "owner_audio_used"):
        if privacy.get(field) is not False:
            raise ValueError(f"final privacy field must be false: {field}")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def _validate_hey_jarvis_migration_evidence(payload: dict[str, Any]) -> None:
    """Validate the synthetic Hey Jarvis migration gate and owner boundary."""

    required = {
        "schema_version",
        "phase",
        "migration",
        "wake_phrase",
        "backend",
        "model_repository",
        "model_revision",
        "model_commit",
        "artifact_filename",
        "model_sha256",
        "license",
        "runtime_version",
        "capture_frame_ms",
        "capture_frame_samples",
        "sample_rate_hz",
        "production_capture_equivalent",
        "synthetic_only",
        "owner_audio_used",
        "raw_audio_retained",
        "temporary_audio_removed",
        "historical_evidence",
        "owner_gate_policy",
        "calibration_split",
        "held_out_split",
        "threshold_sweep",
        "threshold",
        "required_hits_in_three_frames",
        "recall",
        "negative_attempts",
        "false_activations",
        "far",
        "false_activations_per_hour",
        "software_gate",
        "production_gate_passed",
        "one_breath_command_pass",
        "barge_in_pass",
        "follow_up_pass",
        "right_ctrl_pass",
        "ptt_pass",
        "privacy_pass",
        "phase_11_boundary",
        "implementation_commit",
        "final_head",
        "decision",
        "owner_physical_gate_ready",
    }
    if missing := required - payload.keys():
        raise ValueError(f"missing Hey Jarvis migration fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-hey-jarvis/v1" or payload["phase"] != 10:
        raise ValueError("unsupported Hey Jarvis migration schema")
    if payload["wake_phrase"] != "Hey Jarvis":
        raise ValueError("Hey Jarvis migration must use the exact canonical phrase")
    if payload["backend"] not in {
        "openwakeword_single_stage",
        "openwakeword_candidate_whisper_verifier",
    }:
        raise ValueError("Hey Jarvis migration backend is not approved")
    if (
        payload["model_repository"] != "https://github.com/dscripka/openWakeWord"
        or payload["model_revision"] != "v0.5.1"
        or payload["model_commit"] != "1eec2158c5c54150ac5f4c15065adacb1003b1e7"
        or payload["artifact_filename"] != "hey_jarvis_v0.1.onnx"
        or payload["model_sha256"]
        != "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"
        or payload["license"] != "CC-BY-NC-SA-4.0"
    ):
        raise ValueError("Hey Jarvis artifact provenance is not the pinned official identity")
    for field in ("implementation_commit", "final_head"):
        if not isinstance(payload[field], str) or not SHA_PATTERN.fullmatch(payload[field]):
            raise ValueError(f"Hey Jarvis {field} must be a full lowercase Git SHA")
    if payload["implementation_commit"] != payload["final_head"]:
        raise ValueError("Hey Jarvis implementation and final head must match")
    if (
        payload["capture_frame_ms"] != 80
        or payload["capture_frame_samples"] != 1280
        or payload["sample_rate_hz"] != 16_000
        or payload["production_capture_equivalent"] is not True
    ):
        raise ValueError("Hey Jarvis capture contract is not production-equivalent")
    for field, expected in (
        ("synthetic_only", True),
        ("owner_audio_used", False),
        ("raw_audio_retained", False),
        ("temporary_audio_removed", True),
    ):
        if payload[field] is not expected:
            raise ValueError(f"Hey Jarvis evidence must set {field}={expected}")
    history = _require_mapping(payload["historical_evidence"], "historical_evidence")
    if (
        history.get("previous_primary_phrase") != "Jarvis"
        or history.get("previous_physical_evidence_preserved") is not True
        or history.get("previous_bare_jarvis_owner_gate_is_historical") is not True
    ):
        raise ValueError("historical bare Jarvis evidence must remain explicitly preserved")
    policy = _require_mapping(payload["owner_gate_policy"], "owner_gate_policy")
    if (
        policy.get("positive_wake_activations_min") != 3
        or policy.get("positive_wake_activations_max") != 5
        or policy.get("representative_negative_cases_max") != 5
        or policy.get("no_20_round_owner_calibration") is not True
    ):
        raise ValueError("Hey Jarvis owner gate policy is not the compact accepted policy")
    calibration = _require_mapping(payload["calibration_split"], "calibration_split")
    held_out = _require_mapping(payload["held_out_split"], "held_out_split")
    if calibration.get("attempts", 0) <= 0 or calibration.get("positive_attempts", 0) <= 0:
        raise ValueError("Hey Jarvis calibration split is incomplete")
    if held_out.get("positive_attempts", 0) < 100 or held_out.get("negative_attempts", 0) < 1000:
        raise ValueError(
            "Hey Jarvis held-out split must contain at least 100 positives and 1000 negatives"
        )
    positives = held_out["positive_attempts"]
    detections = payload["positive_detections"]
    negatives = payload["negative_attempts"]
    false_activations = payload["false_activations"]
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (positives, detections, negatives, false_activations)
    ):
        raise ValueError("Hey Jarvis counts must be non-negative integers")
    if detections > positives or false_activations > negatives:
        raise ValueError("Hey Jarvis counts exceed their denominators")
    if payload["recall"] != round(detections / max(1, positives), 4):
        raise ValueError("Hey Jarvis recall does not reconcile")
    if payload["far"] != round(false_activations / max(1, negatives), 4):
        raise ValueError("Hey Jarvis FAR does not reconcile")
    for field in ("threshold", "recall", "far", "false_activations_per_hour"):
        if not isinstance(payload[field], (int, float)) or payload[field] < 0:
            raise ValueError(f"Hey Jarvis metric is invalid: {field}")
    required_hits = payload.get(
        "required_hits_in_window", payload.get("required_hits_in_three_frames")
    )
    if (
        not 0.0 <= payload["threshold"] <= 1.0
        or not isinstance(required_hits, int)
        or not 1 <= required_hits <= 5
    ):
        raise ValueError("Hey Jarvis threshold policy is invalid")
    sweep = payload["threshold_sweep"]
    if not isinstance(sweep, list) or not sweep:
        raise ValueError("Hey Jarvis threshold sweep is required")
    for row in sweep:
        item = _require_mapping(row, "Hey Jarvis threshold sweep row")
        if not {"threshold", "recall", "far", "false_activations"}.issubset(item):
            raise ValueError("Hey Jarvis threshold sweep row is incomplete")
    gate = _require_mapping(payload["software_gate"], "software_gate")
    if (
        gate.get("minimum_recall") != 0.98
        or gate.get("minimum_far") != 0.0025
        or gate.get("target_recall") != 0.99
        or gate.get("target_far") != 0.001
        or gate.get("actual_recall") != payload["recall"]
        or gate.get("actual_far") != payload["far"]
    ):
        raise ValueError("Hey Jarvis software gate does not reconcile")
    if payload["production_gate_passed"] is not payload["owner_physical_gate_ready"]:
        raise ValueError("Hey Jarvis owner readiness does not reconcile")
    if payload["production_gate_passed"]:
        if payload["recall"] < 0.99 or payload["far"] > 0.001:
            raise ValueError("Hey Jarvis production gate claims pass below the required metrics")
        if payload["decision"] != "hey_jarvis_software_gate_passed":
            raise ValueError("Hey Jarvis pass decision is invalid")
    elif payload["decision"] != "blocked_hey_jarvis_software_gate":
        raise ValueError("Hey Jarvis blocked decision is invalid")
    for field in (
        "one_breath_command_pass",
        "barge_in_pass",
        "follow_up_pass",
        "right_ctrl_pass",
        "ptt_pass",
        "privacy_pass",
    ):
        if payload[field] is not True:
            raise ValueError(f"Hey Jarvis deterministic regression must pass: {field}")
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def _validate_owner_verifier_evidence(payload: dict[str, Any]) -> None:
    """Validate the pre-enrollment owner-specific verifier boundary."""

    required = {
        "schema_version",
        "phase",
        "wake_phrase",
        "backend",
        "software_tested_commit",
        "final_head",
        "base_model",
        "owner_verifier",
        "historical_whisper_verifier",
        "software_gate",
        "owner_gate_policy",
        "privacy",
        "production_gate_passed",
        "owner_enrollment_required",
        "phase_11_boundary",
    }
    if missing := required - payload.keys():
        raise ValueError(f"missing owner verifier evidence fields: {sorted(missing)}")
    if payload["schema_version"] != "phase-10-owner-verifier/v1" or payload["phase"] != 10:
        raise ValueError("unsupported owner verifier evidence schema")
    if payload["wake_phrase"] != "Hey Jarvis":
        raise ValueError("owner verifier evidence must use the exact Hey Jarvis phrase")
    if payload["backend"] != "openwakeword_owner_verifier":
        raise ValueError("owner verifier evidence backend is invalid")
    for field in ("software_tested_commit", "final_head"):
        if not isinstance(payload[field], str) or not SHA_PATTERN.fullmatch(payload[field]):
            raise ValueError(f"owner verifier {field} must be a full Git SHA")
    model = _require_mapping(payload["base_model"], "owner verifier base model")
    expected_model = {
        "repository": "https://github.com/dscripka/openWakeWord",
        "revision": "v0.5.1",
        "commit": "1eec2158c5c54150ac5f4c15065adacb1003b1e7",
        "filename": "hey_jarvis_v0.1.onnx",
        "sha256": "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
        "engine_license": "Apache-2.0",
        "pretrained_model_license": "CC-BY-NC-SA-4.0",
    }
    for field, expected in expected_model.items():
        if model.get(field) != expected:
            raise ValueError(f"owner verifier base model identity mismatch: {field}")
    owner = _require_mapping(payload["owner_verifier"], "owner verifier")
    if (
        owner.get("schema_version") != "phase-10-hey-jarvis-owner-verifier/v1"
        or owner.get("artifact_filename") != "verifier.joblib"
        or owner.get("artifact_committed") is not False
        or owner.get("artifact_downloaded") is not False
        or owner.get("training_api") != "openwakeword.train_custom_verifier"
        or owner.get("runtime") != "openwakeword==0.6.0; custom_verifier_model"
        or owner.get("status") != "owner_enrollment_required"
        or owner.get("owner_audio_used") is not False
        or owner.get("raw_audio_retained") is not False
    ):
        raise ValueError("owner verifier profile contract is invalid")
    if owner.get("profile_path") != "%LOCALAPPDATA%/BMO/voice/wake/hey_jarvis_owner_verifier":
        raise ValueError("owner verifier profile path must remain sanitized and canonical")
    validation = _require_mapping(owner.get("validation"), "owner verifier validation")
    if (
        validation.get("status") != "not_run_until_owner_enrollment"
        or validation.get("positive_train_attempts") != 3
        or validation.get("positive_reserved_validation_attempts") != 2
        or validation.get("raw_audio_retained") is not False
    ):
        raise ValueError("owner verifier enrollment split is invalid")
    historical = _require_mapping(
        payload["historical_whisper_verifier"], "historical Whisper verifier"
    )
    if (
        historical.get("preserved") is not True
        or historical.get("decision") != "historical_not_active_wake_backend"
    ):
        raise ValueError("historical Whisper wake evidence must remain preserved and inactive")
    gate = _require_mapping(payload["software_gate"], "owner verifier software gate")
    if (
        gate.get("owner_validation_required") is not True
        or gate.get("owner_enrollment_complete") is not False
        or gate.get("owner_physical_gate_authorized") is not False
        or gate.get("owner_final_recall") is not None
        or gate.get("owner_final_false_activation_rate") is not None
        or gate.get("owner_final_continuous_faph") is not None
    ):
        raise ValueError("owner verifier software gate must remain pending enrollment")
    policy = _require_mapping(payload["owner_gate_policy"], "owner verifier owner policy")
    if (
        policy.get("positive_wake_activations_min") != 3
        or policy.get("positive_wake_activations_max") != 5
        or policy.get("representative_negative_cases_max") != 5
        or policy.get("no_20_round_owner_calibration") is not True
    ):
        raise ValueError("owner verifier owner gate is not the compact policy")
    privacy = _require_mapping(payload["privacy"], "owner verifier privacy")
    for field in (
        "owner_audio_used",
        "raw_audio_retained",
        "raw_audio_committed",
        "raw_audio_logged",
        "profile_owner_local_only",
        "temporary_audio_removed",
    ):
        expected_privacy = not (field.startswith("raw_audio") or field == "owner_audio_used")
        if privacy.get(field) is not expected_privacy:
            raise ValueError(f"owner verifier privacy field is invalid: {field}")
    if (
        payload["production_gate_passed"] is not False
        or payload["owner_enrollment_required"] is not True
    ):
        raise ValueError(
            "owner verifier evidence cannot authorize production or physical acceptance"
        )
    if payload["phase_11_boundary"] != "NOT_STARTED":
        raise ValueError("Phase 11 must remain NOT_STARTED")
    _walk_forbidden(payload)


def validate_evidence(payload: dict[str, Any]) -> None:
    """Reject incomplete, non-sanitized, or contradictory Phase 10 evidence."""

    schema = payload.get("schema_version")
    if schema == "phase-10-stateful-wake-isolation/v1":
        _validate_stateful_wake_isolation_evidence(payload)
    elif schema == "phase-10-streaming-wake-path/v1":
        _validate_streaming_wake_path_evidence(payload)
    elif schema == "phase-10-wake-verifier-optimization/v1":
        _validate_wake_verifier_optimization_evidence(payload)
    elif schema == "phase-10-wake-backend-reselection/v1":
        _validate_wake_backend_reselection_evidence(payload)
    elif schema == "phase-10-voice-v2-evidence/v1":
        _validate_v2_evidence(payload)
    elif schema == "phase-10-wake-cascade/v1":
        _validate_cascade_evidence(payload)
    elif schema == "phase-10-hey-jarvis-final/v1":
        _validate_final_hey_jarvis_evidence(payload)
    elif schema == "phase-10-hey-jarvis/v1":
        _validate_hey_jarvis_migration_evidence(payload)
    elif schema == "phase-10-owner-verifier/v1":
        _validate_owner_verifier_evidence(payload)
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
