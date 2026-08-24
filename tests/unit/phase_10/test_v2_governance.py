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


def test_v2_evidence_has_no_raw_audio_or_credentials() -> None:
    evidence = (ROOT / "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json").read_text(
        encoding="utf-8"
    )
    lowered = evidence.casefold()
    assert '"raw_audio_persisted": false' in lowered
    assert '"credential_in_evidence": false' in lowered
    assert "pcm" not in lowered
