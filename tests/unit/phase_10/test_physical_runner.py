from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

import pytest

from personal_ai_os.voice.contracts import AudioFrame, VoiceState
from scripts.phase_10.run_physical_gate import (
    NoMicrophoneAudio,
    ResourceMonitor,
    _audio_level,
    _base_evidence,
    _derive_presence_calibration,
    _finish_live_capture,
    _load_stage_a_checkpoint,
    _privacy_scan,
    _prompt_capture,
    _sanitize_failure,
    _save_stage_a_checkpoint,
    _self_trigger_round,
    _start_live_capture,
    _verify_local_tts_playback,
)


def test_physical_evidence_starts_blocked_without_a_tested_commit() -> None:
    args = argparse.Namespace(
        base_main_sha="1" * 40,
        governance_correction_commit="2" * 40,
        software_tested_commit="3" * 40,
    )

    evidence = _base_evidence(args)

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

    with pytest.raises(NoMicrophoneAudio, match="NO_AUDIO"):
        _prompt_capture(SilentSound(), "normal pronunciation", 1.0, retries=1)


def test_presence_calibration_distinguishes_silence_quiet_speech_and_noise() -> None:
    calibration = _derive_presence_calibration({"rms": 0.0001, "peak": 0.0004})

    assert calibration.classify({"rms": 0.0001, "peak": 0.0004}) == "NO_AUDIO"
    assert calibration.classify({"rms": 0.0002, "peak": 0.0007}) == "NO_AUDIO"
    assert calibration.classify({"rms": 0.0005, "peak": 0.0015}) == "MEASURABLE_SIGNAL"
    assert calibration.classify({"rms": 0.004, "peak": 0.02}) == "SPEECH_PRESENT"


def test_prompt_capture_sends_quiet_measurable_signal_to_wake_inference(
    monkeypatch: object,
) -> None:
    class QuietSound:
        def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
            del seconds
            return (AudioFrame(b"\x10\x00" * 1600),)

    monkeypatch.setattr("scripts.phase_10.run_physical_gate._countdown", lambda _prompt: None)
    calibration = _derive_presence_calibration({"rms": 0.0001, "peak": 0.0004})

    frames = _prompt_capture(
        QuietSound(),
        "quiet Jarvis",
        1.0,
        retries=0,
        presence=calibration,
    )

    assert frames


def test_audio_level_matches_signed_int16_normalized_range() -> None:
    frames = (AudioFrame(b"\x00\x00\xff\x7f\x00\x80"),)

    level = _audio_level(frames)

    assert level["peak"] == 1.0
    assert 0.81 < level["rms"] < 0.82


def test_self_trigger_runs_playback_and_capture_without_deadlock(monkeypatch: object) -> None:
    finished = threading.Event()

    class FakeSound:
        def stream_input(
            self,
            callback: object,
            *,
            seconds: float,
            stop_event: threading.Event | None = None,
        ) -> None:
            assert seconds == 3.0
            del stop_event
            assert callable(callback)
            callback(AudioFrame(b"\x00\x00" * 1600))

        def play(self, frames: tuple[AudioFrame, ...]) -> None:
            assert frames
            finished.set()

    class FakePipeline:
        def __init__(self) -> None:
            self.machine = type("FakeMachine", (), {"state": VoiceState.SLEEPING})()
            self.tts = type(
                "FakeTts", (), {"synthesize": lambda _self, _text: (AudioFrame(b"\x01\x00"),)}
            )()
            self.wake_word = type("FakeWake", (), {"reset": lambda _self: None})()
            self.pre_roll = type(
                "FakePreRoll", (), {"duration_seconds": 0.0, "clear": lambda _self: None}
            )()

        @property
        def state(self) -> VoiceState:
            return self.machine.state

        def on_capture_frame(self, _frame: AudioFrame) -> bool:
            return False

        def sleep(self) -> None:
            self.machine.state = VoiceState.SLEEPING

        @property
        def pipeline(self) -> FakePipeline:
            return self

        def on_frame(self, _frame: AudioFrame) -> VoiceState:
            return self.state

    monkeypatch.setattr("scripts.phase_10.run_physical_gate._countdown", lambda _prompt: None)

    detected, latency = _self_trigger_round(FakePipeline(), FakeSound())

    assert detected is False
    assert latency >= 0
    assert finished.is_set()


def test_live_capture_delivers_frames_to_the_conversation_loop() -> None:
    class FakeSound:
        def stream_input(
            self,
            callback: object,
            *,
            seconds: float,
            stop_event: threading.Event | None = None,
        ) -> None:
            assert seconds == 0.2
            del stop_event
            assert callable(callback)
            callback(AudioFrame(b"\x01\x00" * 1600))

    class FakeLoop:
        state = VoiceState.SPEAKING

        def on_frame(self, _frame: AudioFrame) -> VoiceState:
            self.state = VoiceState.LISTENING
            return self.state

    thread, stop_event, result = _start_live_capture(FakeLoop(), FakeSound(), 0.2)
    result = _finish_live_capture(thread, stop_event, result, timeout_seconds=2.0)

    assert result["frame_count"] == 1
    assert result["first_barge_in_ms"] is not None


def test_physical_runner_builds_the_coordinator_and_has_no_low_level_barge_bypass() -> None:
    script = (
        Path(__file__).resolve().parents[3] / "scripts/phase_10/run_physical_gate.py"
    ).read_text(encoding="utf-8")

    assert "build_local_conversation_loop" in script
    assert "build_local_runtime" not in script
    assert "pipeline.process_utterance" not in script
    assert "pipeline.barge_in" not in script


def test_physical_script_uses_speech_gated_wake_backend_without_enrollment() -> None:
    script_path = Path(__file__).resolve().parents[3] / "scripts/phase_10/run_local_acceptance.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert '"--wake-word-backend", "speech_gated_faster_whisper"' in script
    assert '"--wake-model", $wakeModel' in script
    assert "owner_verifier" not in script
    assert "openwakeword_owner_verifier" not in script


def test_stage_a_uses_production_capture_path_for_each_streaming_frame() -> None:
    script_path = Path(__file__).resolve().parents[3] / "scripts/phase_10/run_physical_gate.py"
    script = script_path.read_text(encoding="utf-8")
    stage_a = script[
        script.index("def _stage_a_wake_trials") : script.index("def _self_trigger_round")
    ]

    assert "loop.on_frame(frame)" in stage_a
    assert "pipeline.on_capture_frame(frame)" not in stage_a


def test_physical_runner_uses_bounded_speech_gated_defaults() -> None:
    from personal_ai_os.voice.runtime import VoiceRuntimeConfig

    config = VoiceRuntimeConfig(
        wake_word_backend="speech_gated_faster_whisper",
        wake_word_model="base.en",
        wake_word_device="cpu",
        wake_word_compute_type="int8",
        wake_word_beam_size=1,
        wake_word_hotwords=None,
        stt_model="faster-whisper-medium",
        arabic_tts_model=Path("ar.onnx"),
        arabic_tts_tokens=Path("ar.tokens"),
        english_tts_model=Path("en.onnx"),
        english_tts_tokens=Path("en.tokens"),
        tts_data_dir=Path("data"),
    )
    assert config.wake_word_backend == "speech_gated_faster_whisper"
    assert config.wake_word_model == "base.en"
    assert config.wake_word_device == "cpu"
    assert config.wake_word_compute_type == "int8"
    assert config.wake_word_beam_size == 1
    assert config.wake_word_hotwords is None


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
    evidence = _base_evidence(args)
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
        {"normal Hey Jarvis": {"attempted": 5, "detected": 5, "required": 1}},
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
    evidence = _base_evidence(args)
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
