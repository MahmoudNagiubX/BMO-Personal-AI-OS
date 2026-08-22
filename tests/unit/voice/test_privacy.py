from __future__ import annotations

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.privacy import BoundedAudioBuffer


def frame(seconds: float = 0.1) -> AudioFrame:
    return AudioFrame(b"\x00\x00" * int(16_000 * seconds))


def test_buffer_is_bounded_and_take_clears_pcm_references() -> None:
    buffer = BoundedAudioBuffer(max_seconds=0.2, max_bytes=10_000)
    buffer.append(frame())
    buffer.append(frame())
    buffer.append(frame())
    assert buffer.duration_seconds <= 0.2
    assert buffer.take()
    assert buffer.bytes_used == 0
    assert buffer.duration_seconds == 0


def test_buffer_cleans_up_on_failure() -> None:
    buffer = BoundedAudioBuffer()
    try:
        with buffer.lifetime():
            buffer.append(frame())
            raise RuntimeError("synthetic adapter failure")
    except RuntimeError:
        pass
    assert buffer.bytes_used == 0
