from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v2_voice_governance_is_explicit_and_phase11_is_deferred() -> None:
    phase = (ROOT / "docs/phases/PHASE_10_JARVIS_VOICE_CORE.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs/adr/0011-jarvis-voice-architecture-v2.md").read_text(encoding="utf-8")
    assert "Vosk" in phase
    assert "double-tap Right Ctrl" in phase
    assert "Smart Turn" in phase
    assert "Raw audio is not stored" in phase
    assert "Vosk" in adr
    assert "Phase 11" in adr
    assert "NOT_STARTED" in adr
    assert "paid" in adr.casefold()
    assert "three to" in phase
    assert "20-round" in phase


def test_v2_owner_gate_policy_is_compact_and_uses_shared_physical_proofs() -> None:
    import json

    evidence = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
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


def test_physical_runner_uses_current_backend_and_compact_wake_gate() -> None:
    runner = (ROOT / "scripts/phase_10/run_physical_gate.py").read_text(encoding="utf-8")
    assert "between 3 and 5" in runner
    assert "between 3 and 20" not in runner
    assert "microWakeWord self-triggered" not in runner
    assert "args.wake_word_backend} self-triggered" in runner
    assert "right_ctrl_double_tap" in runner
    assert "on_capture_frame" in runner


def test_v2_evidence_has_no_raw_audio_or_credentials() -> None:
    evidence = (ROOT / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
        encoding="utf-8"
    )
    lowered = evidence.casefold()
    assert '"raw_audio_persisted": false' in lowered
    assert '"credential_in_evidence": false' in lowered
    assert "pcm" not in lowered
