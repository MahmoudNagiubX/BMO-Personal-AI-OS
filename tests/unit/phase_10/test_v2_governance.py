from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_final_architecture_replaces_retired_runnable_wake_paths() -> None:
    phase = (ROOT / "docs/phases/PHASE_10_JARVIS_VOICE_CORE.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs/adr/0019-final-hey-jarvis-wake-architecture.md").read_text(encoding="utf-8")
    reselection = (ROOT / "docs/adr/0020-hey-jarvis-backend-reselection.md").read_text(
        encoding="utf-8"
    )
    assert "Hey Jarvis" in phase
    assert "openWakeWord" in phase
    assert "faster-whisper" in phase
    assert "three to five" in phase
    assert "20-round owner calibration is" in phase
    assert "historical evidence only" in phase
    assert "Phase 11" in phase and "NOT_STARTED" in phase
    assert "CC-BY-NC-SA-4.0" in adr
    assert "superseded by ADR-0020" in adr
    assert "microWakeWord v2" in reselection
    assert "blocked" in reselection.casefold()

    deleted = (
        "benchmark_vosk_wakeword.py",
        "benchmark_pocketsphinx_wakeword.py",
        "benchmark_sherpa_wakeword.py",
        "train_jarvis_wake_word.py",
        "train_jarvis_micro_wake_word.py",
        "debug_micro_wakeword_scorer.py",
        "enroll_personalized_mfcc.py",
    )
    for name in deleted:
        assert not (ROOT / "scripts/phase_10" / name).exists()
    assert not (ROOT / "scripts/phase_10/benchmark_micro_wakeword.py").exists()
    assert "pymicro-wakeword" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "MicroWakeWordDetector" not in (ROOT / "src/personal_ai_os/voice/adapters.py").read_text(
        encoding="utf-8"
    )


def test_final_evidence_and_runtime_contract_are_explicit() -> None:
    evidence = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_10_HEY_JARVIS_FINAL.json").read_text(
            encoding="utf-8"
        )
    )
    reselection = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_10_WAKE_BACKEND_RESELECTION.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["wake_phrase"] == "Hey Jarvis"
    assert evidence["backend"] == "openwakeword_candidate_whisper_verifier"
    assert evidence["physical"]["status"] == "not_authorized"
    assert evidence["phase_11_boundary"] == "NOT_STARTED"
    assert evidence["production_gate_passed"] is False
    assert reselection["decision"] == "blocked_both_candidates"
    assert reselection["owner_physical_gate_authorized"] is False
    assert reselection["micro_wake_word"]["held_out"]["positive_detections"] == 217
    assert reselection["open_wake_word"]["cascade_held_out"]["positive_detections"] == 489
    runtime = (ROOT / "src/personal_ai_os/voice/runtime.py").read_text(encoding="utf-8")
    assert 'Literal["cascade_openwakeword_whisper"]' in runtime
    assert "VoskWakeWordDetector" not in runtime
    assert "PersonalizedMfcc" not in runtime


def test_owner_gate_is_compact_and_keeps_natural_use_proofs() -> None:
    evidence = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_10_HEY_JARVIS_FINAL.json").read_text(
            encoding="utf-8"
        )
    )
    policy = evidence["physical"]["owner_gate_policy"]
    assert policy["positive_wake_activations_min"] == 3
    assert policy["positive_wake_activations_max"] == 5
    assert policy["no_20_round_owner_calibration"] is True
    assert policy["single_utterance_preroll"] is True
    assert policy["right_ctrl_shared_pipeline"] is True
    assert policy["smart_turn_natural_pause"] is True


def test_physical_runner_uses_active_backend_neutral_error_text() -> None:
    runner = (ROOT / "scripts/phase_10/run_physical_gate.py").read_text(encoding="utf-8")
    assert "between 3 and 5" in runner
    assert "microWakeWord self-triggered" not in runner
    assert "args.wake_word_backend} self-triggered" in runner
    assert "right_ctrl_double_tap" in runner
