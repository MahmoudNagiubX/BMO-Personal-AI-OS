from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

import pytest

from personal_ai_os.voice.contracts import AudioFrame
from scripts.phase_10.run_physical_gate import (
    NoMicrophoneAudio,
    ResourceMonitor,
    _audio_level,
    _base_evidence,
    _load_stage_a_checkpoint,
    _privacy_scan,
    _prompt_capture,
    _sanitize_failure,
    _save_stage_a_checkpoint,
    _self_trigger_round,
    _verify_local_tts_playback,
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


def test_audio_level_matches_signed_int16_normalized_range() -> None:
    frames = (AudioFrame(b"\x00\x00\xff\x7f\x00\x80"),)

    level = _audio_level(frames)

    assert level["peak"] == 1.0
    assert 0.81 < level["rms"] < 0.82


def test_self_trigger_runs_playback_and_capture_without_deadlock(monkeypatch: object) -> None:
    finished = threading.Event()

    class FakeSound:
        def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
            assert seconds == 3.0
            return (AudioFrame(b"\x00\x00" * 1600),)

        def play(self, frames: tuple[AudioFrame, ...]) -> None:
            assert frames
            finished.set()

    class FakePipeline:
        tts = type("FakeTts", (), {"synthesize": lambda _self, _text: (AudioFrame(b"\x01\x00"),)})()
        wake_word = type("FakeWake", (), {"reset": lambda _self: None})()

        @staticmethod
        def on_wake_frame(_frame: AudioFrame) -> bool:
            return False

        @staticmethod
        def sleep() -> None:
            return None

    monkeypatch.setattr("scripts.phase_10.run_physical_gate._countdown", lambda _prompt: None)

    detected, latency = _self_trigger_round(FakePipeline(), FakeSound())

    assert detected is False
    assert latency >= 0
    assert finished.is_set()


def test_tts_preflight_exercises_synthesis_playback_and_capture() -> None:
    class FakeSound:
        def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
            assert seconds == 1.5
            return (AudioFrame(b"\x01\x00" * 1600),)

        @staticmethod
        def play(frames: tuple[AudioFrame, ...]) -> None:
            assert frames

    class FakePipeline:
        tts = type("FakeTts", (), {"synthesize": lambda _self, _text: (AudioFrame(b"\x01\x00"),)})()

    result = _verify_local_tts_playback(FakePipeline(), FakeSound())

    assert result["status"] == "pass"
    assert result["raw_audio_retained"] is False
    assert result["captured_frame_count"] == 1


def test_playback_failure_is_sanitized_without_private_path() -> None:
    failure = _sanitize_failure(OSError("OutputStream failed at C:\\Users\\owner\\voice.wav"))

    assert failure.startswith("playback device failure:")
    assert "C:\\Users" not in failure
    assert "<path>" in failure


def test_stage_a_checkpoint_round_trips_only_scalar_evidence(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    args = argparse.Namespace(
        base_main_sha="1" * 40,
        governance_correction_commit="2" * 40,
        software_tested_commit="3" * 40,
    )
    evidence = _base_evidence(args, "4" * 64, "5" * 64)
    monkeypatch.setattr(
        "scripts.phase_10.run_physical_gate._resources",
        lambda: {"cpu_percent": 4.0, "ram_used_mib": 100.0},
    )
    output = tmp_path / "evidence.json"

    _save_stage_a_checkpoint(
        evidence,
        output,
        5,
        0,
        [10.0, 12.0],
        {"normal bare Jarvis": {"attempted": 5, "detected": 5}},
        {"English non-wake speech": {"attempted": 1, "false_activations": 0}},
    )
    loaded = _load_stage_a_checkpoint(output, "3" * 40)

    physical = loaded["physical_gate"]
    assert physical["stage_a_complete"] is True
    assert physical["recall"] == 1.0
    assert physical["false_activation_count"] == 0
    assert physical["checkpoint_resource_metrics"]["cpu_percent"] == 4.0
    assert "pcm" not in output.read_text(encoding="utf-8").casefold()


def test_stage_a_checkpoint_rejects_obsolete_long_owner_policy(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    args = argparse.Namespace(
        base_main_sha="1" * 40,
        governance_correction_commit="2" * 40,
        software_tested_commit="3" * 40,
    )
    evidence = _base_evidence(args, "4" * 64, "5" * 64)
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        "scripts.phase_10.run_physical_gate._resources",
        lambda: {"cpu_percent": 4.0, "ram_used_mib": 100.0},
    )
    with pytest.raises(ValueError, match="between 3 and 5"):
        _save_stage_a_checkpoint(
            evidence,
            output,
            20,
            0,
            [10.0],
            {"historical": {"attempted": 20, "detected": 20}},
            {},
            rounds=20,
        )
