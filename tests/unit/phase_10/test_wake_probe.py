from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.wake_cascade import WakeVerification
from scripts.phase_10 import run_hey_jarvis_reference_probe as probe


class _FakeSound:
    input_device_name = "Synthetic microphone"
    sample_rate_hz = 16_000

    def __init__(self, **_kwargs: Any) -> None:
        return None

    def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
        assert seconds == 2.0
        return (AudioFrame(b"\x00\x00" * 160),)


class _FakeDetector:
    def __init__(self, accepted: bool = False) -> None:
        self.accepted = accepted
        self._reset_count = 0
        self.last_verification: WakeVerification | None = None
        self.last_failure_category: str | None = None
        self.verifier_invocations = 0

    def detected(self, _frame: AudioFrame) -> bool:
        accepted = self.accepted if self._reset_count == 0 else self._reset_count <= 3
        self.verifier_invocations = 1
        self.last_verification = WakeVerification(
            accepted=accepted,
            normalized_word_count=2 if accepted else 1,
            wake_token_at_start=accepted,
            latency_ms=2.5,
            failure_category=None if accepted else "wrong_first_token",
        )
        self.last_failure_category = self.last_verification.failure_category
        return accepted

    def reset(self) -> None:
        self._reset_count += 1
        self.last_verification = None
        self.last_failure_category = None
        self.verifier_invocations = 0


def test_probe_reports_sanitized_verification_metrics(monkeypatch: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    detector = _FakeDetector(accepted=True)

    result = probe._capture_trial(_FakeSound(), detector)

    assert result["accepted"] is True
    assert result["verifier_invocations"] == 1
    assert result["verification_latency_ms"] == 2.5
    assert "transcript" not in result


def test_probe_reports_each_compact_scenario(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(probe, "SoundDeviceBackend", _FakeSound)
    monkeypatch.setattr(probe, "SileroVoiceActivityDetector", lambda: object())
    monkeypatch.setattr(probe, "FasterWhisperWakePhraseRecognizer", lambda **_kwargs: object())

    def detector_factory(**_kwargs: Any) -> _FakeDetector:
        detector_factory.calls += 1
        return _FakeDetector(accepted=detector_factory.calls <= 3)

    detector_factory.calls = 0
    monkeypatch.setattr(probe, "SpeechGatedHeyJarvisDetector", detector_factory)
    monkeypatch.setattr(sys, "argv", ["run_hey_jarvis_reference_probe"])

    assert probe.main() == 0
    output = capsys.readouterr().out
    assert output.count("accepted=True") == 3
    assert output.count("accepted=False") == 5
    assert "raw_audio_retained=false" in output


def test_probe_reports_sanitized_dependency_failure(monkeypatch: Any, capsys: Any) -> None:
    def unavailable(**_kwargs: Any) -> Any:
        raise VoiceDependencyUnavailable("device details must not be printed")

    monkeypatch.setattr(probe, "SoundDeviceBackend", unavailable)
    monkeypatch.setattr(sys, "argv", ["run_hey_jarvis_reference_probe"])
    assert probe.main() == 2
    assert capsys.readouterr().out.strip() == (
        "WAKE_PROBE_BLOCKED reason=audio_or_wake_dependency_unavailable"
    )


def test_probe_is_wake_only_and_never_writes_audio() -> None:
    source = Path(probe.__file__).read_text(encoding="utf-8")
    assert "SileroVoiceActivityDetector" in source
    assert "FasterWhisperWakePhraseRecognizer" in source
    assert "SpeechGatedHeyJarvisDetector" in source
    assert "RhasspyHeyJarvisDetector" not in source
    assert "OpenWakeWord" not in source
    assert "CoreConversationTransport" not in source
    assert "synthesize" not in source
    assert "transcribe" not in source
    assert "write_bytes" not in source
    assert "write_text" not in source
