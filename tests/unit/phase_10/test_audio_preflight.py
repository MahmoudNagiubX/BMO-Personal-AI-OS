from __future__ import annotations

import argparse
from pathlib import Path

from personal_ai_os.voice.contracts import AudioFrame
from scripts.phase_10 import run_audio_preflight


def test_audio_preflight_runs_capture_tts_playback_and_overlap(
    monkeypatch: object,
    capsys: object,
) -> None:
    class FakeSound:
        input_device_name = "TUF Microphone"
        output_device_name = "TUF Headphones"

        def __init__(self, **_kwargs: object) -> None:
            self.play_calls = 0

        def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
            assert seconds == 1.0
            return (AudioFrame(b"\x10\x00" * 1600),)

        def play(self, frames: tuple[AudioFrame, ...]) -> None:
            assert frames
            self.play_calls += 1

        def stop(self) -> None:
            return None

    class FakeTts:
        def __init__(self, **_kwargs: object) -> None:
            return None

        @staticmethod
        def synthesize(_text: str) -> tuple[AudioFrame, ...]:
            return (AudioFrame(b"\x01\x00" * 1600),)

    fake_sound = FakeSound()
    monkeypatch.setattr(run_audio_preflight, "SoundDeviceBackend", lambda **_kwargs: fake_sound)
    monkeypatch.setattr(run_audio_preflight, "SherpaOnnxPiperSynthesizer", FakeTts)
    monkeypatch.setattr(run_audio_preflight, "_countdown", lambda: None)

    run_audio_preflight._run(
        argparse.Namespace(
            input_device="3",
            output_device="4",
            english_tts_model=Path("english.onnx"),
            english_tts_tokens=Path("tokens.txt"),
            tts_data_dir=Path("espeak-ng-data"),
        )
    )

    output = capsys.readouterr().out
    assert "Microphone: TUF Microphone" in output
    assert "Speaker: TUF Headphones" in output
    assert "MICROPHONE_CAPTURE_PASS" in output
    assert "TTS_SYNTHESIS_PASS" in output
    assert "PLAYBACK_STREAM_PASS" in output
    assert "SIMULTANEOUS_CAPTURE_PLAYBACK_PASS" in output
    assert "OWNER_AUDIO_PREFLIGHT_PASS" in output
    assert fake_sound.play_calls == 2
