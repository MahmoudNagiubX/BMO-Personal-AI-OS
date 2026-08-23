from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from personal_ai_os.voice.contracts import AudioFrame
from scripts.phase_10.run_physical_gate import (
    NoMicrophoneAudio,
    ResourceMonitor,
    _base_evidence,
    _privacy_scan,
    _prompt_capture,
)


def test_physical_evidence_starts_blocked_without_a_tested_commit() -> None:
    args = argparse.Namespace(
        base_main_sha="1" * 40,
        governance_correction_commit="2" * 40,
        software_tested_commit="3" * 40,
    )

    evidence = _base_evidence(args, "4" * 64, "5" * 64)

    assert evidence["status"] == "blocked"
    assert evidence["physical_voice_tested_commit"] is None
    assert evidence["physical_gate"]["status"] == "blocked"


def test_privacy_scan_rejects_audio_and_detects_secret_without_logging_it(
    tmp_path: Path,
) -> None:
    audio_root = tmp_path / "runtime"
    audio_root.mkdir()
    (audio_root / "temporary.wav").write_bytes(b"synthetic test marker")
    output = tmp_path / "evidence.json"
    output.write_text(json.dumps({"status": "blocked"}), encoding="utf-8")

    result = _privacy_scan((audio_root,), output, "local-secret")

    assert result["raw_audio_files_found"] == 1
    assert result["raw_audio_persisted"] is False
    assert result["credential_in_evidence"] is False


def test_resource_monitor_returns_scalar_peaks(monkeypatch: object) -> None:
    samples = iter(
        (
            {
                "cpu_percent": 1.0,
                "ram_used_mib": 100.0,
                "memory_used_mib": 10.0,
                "temperature_c": 40.0,
            },
            {
                "cpu_percent": 7.0,
                "ram_used_mib": 120.0,
                "memory_used_mib": 20.0,
                "temperature_c": 50.0,
            },
        )
    )

    monkeypatch.setattr(
        "scripts.phase_10.run_physical_gate._resources",
        lambda: next(samples),
    )
    monitor = ResourceMonitor(interval_seconds=1000.0)
    monitor.start()
    result = monitor.stop()

    assert result["peak_cpu_percent"] == 7.0
    assert result["peak_ram_used_mib"] == 120.0
    assert result["peak_gpu_memory_used_mib"] == 20.0
    assert result["peak_gpu_temperature_c"] == 50.0


def test_prompt_capture_retries_silent_capture_without_counting_a_wake_miss(
    monkeypatch: object,
) -> None:
    class FakeSound:
        def __init__(self) -> None:
            self.calls = 0

        def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
            del seconds
            self.calls += 1
            pcm = b"\x00\x00" * 1600 if self.calls == 1 else b"\xe8\x03" * 1600
            return (AudioFrame(pcm),)

    monkeypatch.setattr("scripts.phase_10.run_physical_gate._countdown", lambda _prompt: None)
    sound = FakeSound()

    frames = _prompt_capture(sound, "normal pronunciation", 1.0, retries=1)

    assert sound.calls == 2
    assert frames[0].pcm_s16le == b"\xe8\x03" * 1600


def test_prompt_capture_reports_missing_audio_separately_from_wake_miss(
    monkeypatch: object,
) -> None:
    class SilentSound:
        def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
            del seconds
            return (AudioFrame(b"\x00\x00" * 1600),)

    monkeypatch.setattr("scripts.phase_10.run_physical_gate._countdown", lambda _prompt: None)

    with pytest.raises(NoMicrophoneAudio, match="no microphone audio"):
        _prompt_capture(SilentSound(), "normal pronunciation", 1.0, retries=1)
