from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v2_voice_governance_is_explicit_and_phase11_is_deferred() -> None:
    phase = (ROOT / "docs/phases/PHASE_10_JARVIS_VOICE_CORE.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs/adr/0011-jarvis-voice-architecture-v2.md").read_text(encoding="utf-8")
    recovery_adr = (ROOT / "docs/adr/0012-personalized-mfcc-dtw-wake.md").read_text(
        encoding="utf-8"
    )
    comparison_adr = (ROOT / "docs/adr/0013-wakeforge-comparative-evaluation.md").read_text(
        encoding="utf-8"
    )
    cascade_adr = (ROOT / "docs/adr/0014-two-stage-wake-cascade.md").read_text(encoding="utf-8")
    assert "Vosk" in phase
    assert "double-tap Right Ctrl" in phase
    assert "Smart Turn" in phase
    assert "Raw audio is not stored" in phase
    assert "Vosk" in adr
    assert "personalized MFCC/DTW" in recovery_adr
    assert "no pretrained wake or embedding weights" in recovery_adr
    assert "Phase 11" in adr
    assert "NOT_STARTED" in adr
    assert "paid" in adr.casefold()
    assert "three to" in phase
    assert "20-round" in phase
    assert "PersonalizedMfccDtwWakeWordDetector" in phase
    assert "WakeForge" in comparison_adr
    assert "owner enrollment" in comparison_adr
    assert "neither backend" in comparison_adr.casefold()
    assert "two-stage" in cascade_adr
    assert "93.33%" in cascade_adr
    assert "Phase 11" in cascade_adr


def test_v2_owner_gate_policy_is_compact_and_uses_shared_physical_proofs() -> None:
    import json

    evidence = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
            encoding="utf-8"
        )
    )
    policy = evidence["physical"]["owner_gate_policy"]
    assert evidence["wake_backend"] == "personalized_mfcc_dtw"
    assert set(evidence["wake_backend_history"]) == {
        "openwakeword",
        "microwakeword",
        "vosk",
        "sherpa_kws",
        "pocketsphinx",
        "local_wake_embedding",
    }
    assert evidence["software"]["mfcc_weight_free"] is True
    assert policy["positive_wake_activations_min"] == 3
    assert policy["positive_wake_activations_max"] == 5
    assert policy["no_20_round_owner_calibration"] is True
    assert policy["single_utterance_preroll"] is True
    assert policy["right_ctrl_shared_pipeline"] is True
    assert policy["smart_turn_natural_pause"] is True

    comparison = evidence["software"]["wake_backend_comparison"]
    assert comparison["wake_word"] == "Jarvis"
    assert comparison["wakeforge_revision"] == "1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7"
    assert comparison["winner"] == "none"
    assert comparison["owner_enrollment_justified"] is False
    assert comparison["source_policy"]["hugging_face_datasets_used"] is False

    cascade = evidence["software"]["wake_cascade"]
    assert cascade["schema_version"] == "phase-10-wake-cascade/v1"
    assert cascade["benchmark_script_commit"] == "b5dcd69bbd235d63f8ae0c66a2f0843428a8977c"
    assert cascade["winner"] == "none"
    assert cascade["decision"] == "blocked_software_operating_point"
    assert cascade["final_recall_best"] == 0.9333
    assert cascade["final_false_activation_rate_best"] == 0.0
    assert cascade["owner_enrollment_justified"] is False
    assert cascade["cuda_attempt"] == "blocked_missing_cublas64_12_dll"
    assert evidence["phase_11_boundary"] == "NOT_STARTED"

    cascade_evidence = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_10_WAKE_CASCADE.json").read_text(
            encoding="utf-8"
        )
    )
    assert cascade_evidence["corpus"]["attempts"] == 370
    assert cascade_evidence["corpus"]["held_out_for_all_experiments"] is True
    assert cascade_evidence["verifiers"]["small"]["model"]["revision"] == (
        "536b0662742c02347bc0e980a01041f333bce120"
    )
    assert cascade_evidence["verifiers"]["small"]["gpu_vram_bytes"] is None


def test_physical_runner_uses_current_backend_and_compact_wake_gate() -> None:
    runner = (ROOT / "scripts/phase_10/run_physical_gate.py").read_text(encoding="utf-8")
    assert "between 3 and 5" in runner
    assert "between 3 and 20" not in runner
    assert "microWakeWord self-triggered" not in runner
    assert "args.wake_word_backend} self-triggered" in runner
    assert "right_ctrl_double_tap" in runner
    assert "on_capture_frame" in runner

    ps_script = (ROOT / "scripts/phase_10/run_local_acceptance.ps1").read_text(encoding="utf-8")
    assert '"vosk"' not in ps_script
    assert "vosk-model" not in ps_script
    assert '--wake-word-backend", "vad_whisper"' in ps_script
    assert "faster-whisper-base.en" in ps_script


def test_v2_evidence_has_no_raw_audio_or_credentials() -> None:
    evidence = (ROOT / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
        encoding="utf-8"
    )
    lowered = evidence.casefold()
    assert '"raw_audio_persisted": false' in lowered
    assert '"credential_in_evidence": false' in lowered
    assert "pcm" not in lowered
