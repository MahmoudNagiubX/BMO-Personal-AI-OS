from __future__ import annotations

import numpy as np

from personal_ai_os.voice.contracts import AudioFrame
from scripts.phase_10.benchmark_stateful_wake_isolation import (
    CAPTURE_FRAME_DURATION_MS,
    CAPTURE_FRAME_SAMPLES,
    _feed_capture_stream,
    _split_into_frames,
)


def test_benchmark_cadence_matches_sounddevice_capture_contract() -> None:
    audio = np.zeros(CAPTURE_FRAME_SAMPLES * 3 + 17, dtype=np.float32)

    frames = _split_into_frames(audio)

    assert CAPTURE_FRAME_DURATION_MS == 80
    assert CAPTURE_FRAME_SAMPLES == 1280
    assert len(frames) == 4
    assert [frame.duration_seconds for frame in frames[:3]] == [0.08, 0.08, 0.08]
    assert all(frame.sample_rate_hz == 16_000 and frame.channels == 1 for frame in frames)


def test_stream_feed_delivers_multiple_incremental_frames_before_detection() -> None:
    delivered: list[AudioFrame] = []

    class _Pipeline:
        def on_capture_frame(self, frame: AudioFrame) -> bool:
            delivered.append(frame)
            return len(delivered) == 3

    audio = np.ones(CAPTURE_FRAME_SAMPLES * 4, dtype=np.float32) * 0.01

    assert _feed_capture_stream(_Pipeline(), audio) is True
    assert len(delivered) == 4
    assert all(frame.duration_seconds == 0.08 for frame in delivered)
