"""Bounded in-memory audio handling with no persistence or logging surface."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from personal_ai_os.voice.contracts import AudioFrame


class BoundedAudioBuffer:
    """Keep only short-lived PCM frames and clear them on every exit path."""

    def __init__(self, *, max_seconds: float = 20.0, max_bytes: int = 2_000_000) -> None:
        if max_seconds <= 0 or max_bytes <= 0:
            raise ValueError("audio bounds must be positive")
        self._max_seconds = max_seconds
        self._max_bytes = max_bytes
        self._frames: deque[AudioFrame] = deque()
        self._bytes = 0

    @property
    def bytes_used(self) -> int:
        return self._bytes

    @property
    def duration_seconds(self) -> float:
        return sum(frame.duration_seconds for frame in self._frames)

    def append(self, frame: AudioFrame) -> None:
        """Add a frame while enforcing both memory and duration bounds."""

        if len(frame.pcm_s16le) > self._max_bytes:
            raise ValueError("audio frame exceeds bounded buffer")
        while self._frames and (
            self._bytes + len(frame.pcm_s16le) > self._max_bytes
            or self.duration_seconds + frame.duration_seconds > self._max_seconds
        ):
            removed = self._frames.popleft()
            self._bytes -= len(removed.pcm_s16le)
        if self._bytes + len(frame.pcm_s16le) > self._max_bytes:
            raise ValueError("audio frame cannot fit bounded buffer")
        self._frames.append(frame)
        self._bytes += len(frame.pcm_s16le)

    def take(self) -> tuple[AudioFrame, ...]:
        """Return frames and immediately clear the buffer."""

        frames = tuple(self._frames)
        self.clear()
        return frames

    def clear(self) -> None:
        """Erase all references to raw audio."""

        self._frames.clear()
        self._bytes = 0

    @contextmanager
    def lifetime(self) -> Iterator[BoundedAudioBuffer]:
        """Guarantee cleanup after success, cancellation, or adapter failure."""

        try:
            yield self
        finally:
            self.clear()


def audio_duration(frames: Sequence[AudioFrame]) -> float:
    """Calculate a scalar metric without exposing PCM data."""

    return sum(frame.duration_seconds for frame in frames)


__all__ = ["BoundedAudioBuffer", "audio_duration"]
