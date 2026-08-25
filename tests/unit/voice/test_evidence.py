from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.phase_10.validate_evidence import validate_evidence


def evidence() -> dict[str, object]:
    return {
        "schema_version": "phase-10-voice-evidence/v1",
        "phase": 10,
        "base_main_sha": "a" * 40,
        "governance_correction_commit": "b" * 40,
        "software_tested_commit": "c" * 40,
        "physical_voice_tested_commit": None,
        "final_head": "d" * 40,
        "status": "pending_physical",
        "software": {
            "unit_tests": True,
            "lint": True,
            "typing": True,
            "governance": True,
            "no_direct_model_bypass": True,
        },
        "physical_gate": {
            "status": "pending",
            "owner_gate_policy": {
                "positive_wake_activations_min": 3,
                "positive_wake_activations_max": 5,
                "representative_negative_cases_max": 5,
                "no_20_round_owner_calibration": True,
                "single_utterance_preroll": True,
                "right_ctrl_shared_pipeline": True,
                "smart_turn_natural_pause": True,
            },
            "wake_word": False,
            "single_utterance_preroll": False,
            "right_ctrl_activation": False,
            "smart_turn_natural_pause": False,
            "follow_up": False,
            "silence_timeout": False,
            "barge_in": False,
            "ptt_fallback": False,
            "arabic_stt": False,
            "english_stt": False,
            "mixed_language_stt": False,
            "no_speech_no_model": False,
            "no_retention_scan": False,
            "resource_metrics": {},
            "latency_metrics": {},
        },
        "dependencies": {
            "wake_word": "openwakeword",
            "vad": "silero-vad",
            "stt": "faster-whisper",
            "arabic_tts": "sherpa-onnx",
            "english_tts": "sherpa-onnx",
            "pipecat": "pipecat-ai",
            "capture_playback": "sounddevice",
        },
        "privacy": {"raw_audio_persisted": False},
        "regressions": {"phase_09": "pending", "qwen_4b": "pending", "qwen_9b": "optional"},
        "phase_11_boundary": "NOT_STARTED",
    }


def test_pending_physical_evidence_is_valid() -> None:
    validate_evidence(evidence())


def test_pass_requires_real_physical_commit_and_all_gate_fields() -> None:
    payload = evidence()
    payload["status"] = "pass"
    with pytest.raises(ValueError, match="physical pass"):
        validate_evidence(payload)


def test_raw_audio_field_is_rejected() -> None:
    payload = evidence()
    payload["audio"] = "never"
    with pytest.raises(ValueError, match="forbidden"):
        validate_evidence(payload)


@pytest.mark.parametrize("field", ["base_main_sha", "software_tested_commit", "final_head"])
def test_commit_evidence_requires_full_lowercase_sha(field: str) -> None:
    payload = evidence()
    payload[field] = "runtime-recorded-after-commit"
    with pytest.raises(ValueError, match=field):
        validate_evidence(payload)


def test_physical_commit_may_be_null_only_while_pending() -> None:
    payload = evidence()
    payload["physical_voice_tested_commit"] = "E" * 40
    with pytest.raises(ValueError, match="physical_voice_tested_commit"):
        validate_evidence(payload)


def test_owner_gate_rejects_long_wake_policy() -> None:
    payload = evidence()
    physical = payload["physical_gate"]
    assert isinstance(physical, dict)
    policy = physical["owner_gate_policy"]
    assert isinstance(policy, dict)
    policy["positive_wake_activations_max"] = 20
    with pytest.raises(ValueError, match="cap activations at 5"):
        validate_evidence(payload)


def test_v2_software_evidence_is_valid() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
            encoding="utf-8"
        )
    )
    validate_evidence(payload)


def test_v2_evidence_rejects_missing_required_software_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
            encoding="utf-8"
        )
    )
    del payload["software"]["authenticated_core_only"]
    with pytest.raises(ValueError, match="missing v2 software fields"):
        validate_evidence(payload)


def test_v2_evidence_requires_a_concrete_wake_backend_comparison() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
            encoding="utf-8"
        )
    )
    del payload["software"]["wake_backend_comparison"]
    with pytest.raises(ValueError, match="missing v2 software fields"):
        validate_evidence(payload)


def test_wake_backend_comparison_cannot_authorize_owner_enrollment() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["software"]["wake_backend_comparison"]["owner_enrollment_justified"] = True
    with pytest.raises(ValueError, match="must not authorize owner enrollment"):
        validate_evidence(payload)


def test_wake_backend_comparison_reconciles_attempt_totals() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["software"]["wake_backend_comparison"]["bmo"]["metrics"]["attempts"] = 1
    with pytest.raises(ValueError, match="attempt totals do not reconcile"):
        validate_evidence(payload)


def test_wake_backend_comparison_file_is_sanitized_and_not_enrollment_ready() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_WAKE_BACKEND_COMPARISON.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["wake_word"] == "Jarvis"
    assert payload["comparison_script_commit"] == "a7ae0f83f9827ce6e62b10ceee8f9cf8244086e8"
    assert payload["wakeforge_revision"] == "1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7"
    assert payload["owner_enrollment_justified"] is False
    assert payload["raw_audio_retained"] is False
    assert payload["bmo"]["attempts"] == (
        payload["bmo"]["positive_attempts"] + payload["bmo"]["negative_attempts"]
    )
    assert payload["wakeforge"]["false_activations"] == payload["wakeforge"]["negative_attempts"]


def cascade_evidence() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    return json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_WAKE_CASCADE.json").read_text(
            encoding="utf-8"
        )
    )


def test_wake_cascade_evidence_is_valid_and_blocked() -> None:
    payload = cascade_evidence()
    validate_evidence(payload)
    assert payload["winner"] == "none"
    assert payload["decision"] == "blocked_software_operating_point"
    assert payload["owner_enrollment_justified"] is False


def test_wake_cascade_cannot_authorize_a_winner_or_owner_enrollment() -> None:
    payload = cascade_evidence()
    payload["winner"] = "wakeforge"
    with pytest.raises(ValueError, match="blocked cascade cannot record"):
        validate_evidence(payload)

    payload = cascade_evidence()
    payload["owner_enrollment_justified"] = True
    with pytest.raises(ValueError, match="must not authorize owner enrollment"):
        validate_evidence(payload)


def test_wake_cascade_threshold_rows_require_concrete_metrics() -> None:
    payload = cascade_evidence()
    verifiers = payload["verifiers"]
    assert isinstance(verifiers, dict)
    small = verifiers["small"]
    assert isinstance(small, dict)
    cascades = small["cascades"]
    assert isinstance(cascades, dict)
    bmo = cascades["bmo_mfcc_dtw"]
    assert isinstance(bmo, dict)
    sweep = bmo["threshold_sweep"]
    assert isinstance(sweep, list)
    del sweep[0]["final_recall"]
    with pytest.raises(ValueError, match="missing cascade metric"):
        validate_evidence(payload)


def test_wake_cascade_rejects_unpinned_verifier_artifact() -> None:
    payload = cascade_evidence()
    verifiers = payload["verifiers"]
    assert isinstance(verifiers, dict)
    small = verifiers["small"]
    assert isinstance(small, dict)
    model = small["model"]
    assert isinstance(model, dict)
    model["revision"] = "not-a-sha"
    with pytest.raises(ValueError, match="verifier revision is not pinned"):
        validate_evidence(payload)


def wake_verifier_evidence() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    return json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_WAKE_VERIFIER_OPTIMIZATION.json").read_text(
            encoding="utf-8"
        )
    )


def test_wake_verifier_optimization_evidence_is_valid_and_blocked() -> None:
    payload = wake_verifier_evidence()
    validate_evidence(payload)
    assert payload["selection"]["decision"] == "blocked_software_operating_point"
    assert payload["owner_enrollment_justified"] is False


def test_wake_verifier_evidence_requires_large_held_out_negative_corpus() -> None:
    payload = wake_verifier_evidence()
    payload["corpus"]["final_held_out"]["negative_attempts"] = 999
    with pytest.raises(ValueError, match="at least 1000 negatives"):
        validate_evidence(payload)


def test_wake_verifier_evidence_rejects_unpinned_model_revision() -> None:
    payload = wake_verifier_evidence()
    payload["models"]["base.en"]["artifact"]["revision"] = "unrelated"
    with pytest.raises(ValueError, match="revision is not pinned"):
        validate_evidence(payload)


def test_wake_verifier_evidence_requires_concrete_final_metrics() -> None:
    payload = wake_verifier_evidence()
    del payload["final_held_out"]["metrics"]["false_activations"]
    with pytest.raises(ValueError, match="missing wake verifier metrics"):
        validate_evidence(payload)


def stateful_wake_isolation_evidence() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    return json.loads(  # type: ignore[no-any-return]
        (root / "docs/phase_reports/evidence/PHASE_10_STATEFUL_WAKE_ISOLATION.json").read_text(
            encoding="utf-8"
        )
    )


def test_stateful_wake_isolation_evidence_is_valid() -> None:
    payload = stateful_wake_isolation_evidence()
    validate_evidence(payload)  # type: ignore[arg-type]
    assert payload["decision"] == "historical_non_streaming_measurement"
    gate = payload["stateful_production_gate"]  # type: ignore[index]
    assert gate["production_reachable_false_activation_rate"] == 0.0
    assert gate["speaking_assistant_playback"]["wake_transitions"] == 0
    assert gate["speaking_assistant_playback"]["verifier_invocations"] == 0
    assert payload["measurement_mode"] == "whole_utterance_frame_pre_fix"
    assert payload["production_capture_equivalent"] is False
    assert payload["owner_physical_gate_ready"] is False
    assert payload["phase_11_boundary"] == "NOT_STARTED"


def test_stateful_wake_isolation_evidence_rejects_speaking_wake_transitions() -> None:
    payload = streaming_wake_path_evidence()
    payload["stateful_production_gate"]["speaking_assistant_playback"]["wake_transitions"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="streaming assistant playback isolation"):
        validate_evidence(payload)  # type: ignore[arg-type]


def test_stateful_wake_isolation_evidence_requires_high_production_recall() -> None:
    payload = streaming_wake_path_evidence()
    payload["stateful_production_gate"]["sleeping_positives"]["recall"] = 0.85  # type: ignore[index]
    with pytest.raises(ValueError, match="streaming sleeping positives"):
        validate_evidence(payload)  # type: ignore[arg-type]


def streaming_wake_path_evidence() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    return json.loads(  # type: ignore[no-any-return]
        (root / "docs/phase_reports/evidence/PHASE_10_STREAMING_WAKE_PATH.json").read_text(
            encoding="utf-8"
        )
    )


def test_streaming_wake_path_evidence_is_valid_and_production_equivalent() -> None:
    payload = streaming_wake_path_evidence()
    validate_evidence(payload)  # type: ignore[arg-type]
    capture = payload["capture_stream"]  # type: ignore[index]
    assert capture["frame_duration_ms"] == 80
    assert capture["production_capture_equivalent"] is True
    sweep = payload["streaming_timing_sweep"]  # type: ignore[index]
    assert sweep["selected_operating_point"] is True
    gate = payload["stateful_production_gate"]  # type: ignore[index]
    assert gate["sleeping_positives"]["recall"] >= 0.95
    assert gate["sleeping_external_negatives"]["false_activation_rate"] <= 0.005


def test_streaming_wake_path_rejects_non_production_capture_claim() -> None:
    payload = streaming_wake_path_evidence()
    payload["capture_stream"]["production_capture_equivalent"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="capture contract"):
        validate_evidence(payload)  # type: ignore[arg-type]


def hey_jarvis_migration_evidence() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    return json.loads(
        (root / "docs/phase_reports/evidence/PHASE_10_HEY_JARVIS_MIGRATION.json").read_text(
            encoding="utf-8"
        )
    )


def test_hey_jarvis_migration_evidence_is_valid_and_blocks_owner_audio() -> None:
    payload = hey_jarvis_migration_evidence()
    validate_evidence(payload)  # type: ignore[arg-type]
    assert payload["wake_phrase"] == "Hey Jarvis"
    assert payload["held_out_split"]["negative_attempts"] >= 3000  # type: ignore[index]
    assert payload["decision"] == "blocked_hey_jarvis_software_gate"
    assert payload["owner_physical_gate_ready"] is False


def test_hey_jarvis_evidence_rejects_phrase_or_gate_claim_tampering() -> None:
    payload = hey_jarvis_migration_evidence()
    payload["wake_phrase"] = "Jarvis"
    with pytest.raises(ValueError, match="canonical phrase"):
        validate_evidence(payload)  # type: ignore[arg-type]

    payload = hey_jarvis_migration_evidence()
    payload["production_gate_passed"] = True
    payload["owner_physical_gate_ready"] = True
    payload["decision"] = "hey_jarvis_software_gate_passed"
    with pytest.raises(ValueError, match="below the required metrics"):
        validate_evidence(payload)  # type: ignore[arg-type]
