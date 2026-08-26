from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
from personal_ai_os.voice.contracts import AudioFrame
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
    threshold = 0.5
    trigger_level = 1
    refractory_seconds = 2.0

    def __init__(self, observer: Any, scores: tuple[float, ...]) -> None:
        self._observer = observer
        self._scores = scores
        self._reset_count = 0

    def detected(self, _frame: AudioFrame) -> bool:
        scores = self._scores if self._reset_count <= 1 else (0.2,)
        for score in scores:
            self._observer(score)
        return False

    def reset(self) -> None:
        self._reset_count += 1

    def close(self) -> None:
        return None


def test_probe_reports_true_peak_probability(monkeypatch: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    observations: list[float] = []
    detector = _FakeDetector(observations.append, (0.1, 0.87, 0.42))

    result = probe._capture_trial(_FakeSound(), detector, observations)

    assert result["peak_probability"] == 0.87
    assert "detection_latency_ms" not in result
    assert "latency_ms" not in result
    assert result["processing_ms"] >= 0


def test_probe_clears_peak_between_scenarios(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(probe, "SoundDeviceBackend", _FakeSound)

    def detector_factory(**kwargs: Any) -> _FakeDetector:
        detector_factory.calls += 1
        scores = (0.1, 0.9) if detector_factory.calls == 1 else (0.2,)
        return _FakeDetector(kwargs["probability_observer"], scores)

    detector_factory.calls = 0
    monkeypatch.setattr(probe, "RhasspyHeyJarvisDetector", detector_factory)
    monkeypatch.setattr(sys, "argv", ["run_hey_jarvis_reference_probe"])

    assert probe.main() == 0
    output = capsys.readouterr().out
    assert output.count("peak_probability=0.9") == 1
    assert output.count("peak_probability=0.2") == 7


def test_probe_reports_sanitized_microphone_failure(monkeypatch: Any, capsys: Any) -> None:
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
    assert "SoundDeviceBackend" in source
    assert "RhasspyHeyJarvisDetector" in source
    assert "CoreConversationTransport" not in source
    assert "synthesize" not in source
    assert "transcribe" not in source
    assert "write_bytes" not in source
    assert "write_text" not in source
