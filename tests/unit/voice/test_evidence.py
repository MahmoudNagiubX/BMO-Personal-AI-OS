from __future__ import annotations

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
            "wake_word": False,
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
