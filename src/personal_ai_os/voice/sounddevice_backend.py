"""Optional Windows capture/playback backend with memory-only audio handling."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
from personal_ai_os.voice.contracts import AudioFrame


class SoundDeviceBackend:
    """Use the local default microphone and speaker without writing audio files."""

    def __init__(self, *, sample_rate_hz: int = 16_000) -> None:
        try:
            self._sounddevice: Any = importlib.import_module("sounddevice")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("sounddevice is not installed") from exc
        self.sample_rate_hz = sample_rate_hz

    def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
        """Capture one bounded in-memory utterance from the default input device."""

        if not 0 < seconds <= 20:
            raise ValueError("capture duration is outside the bounded limit")
        samples = self._sounddevice.rec(
            int(self.sample_rate_hz * seconds),
            samplerate=self.sample_rate_hz,
            channels=1,
            dtype="int16",
            blocking=True,
        )
        raw = samples.tobytes()
        frame_bytes = int(self.sample_rate_hz * 0.08) * 2
        return tuple(
            AudioFrame(raw[offset : offset + frame_bytes], sample_rate_hz=self.sample_rate_hz)
            for offset in range(0, len(raw) - frame_bytes + 1, frame_bytes)
        )

    def play(self, frames: Sequence[AudioFrame]) -> None:
        """Play ephemeral PCM synchronously; another thread may call stop()."""

        if not frames:
            return
        samples = b"".join(frame.pcm_s16le for frame in frames)
        self._sounddevice.play(
            memoryview(samples), samplerate=frames[0].sample_rate_hz, channels=1, blocking=True
        )

    def stop(self) -> None:
        """Stop only the local voice playback stream."""

        self._sounddevice.stop()


def audio_device_count() -> int:
    """Return a scalar device count for sanitized diagnostics."""

    try:
        module: Any = importlib.import_module("sounddevice")
        return len(module.query_devices())
    except (ImportError, OSError):
        return 0


__all__ = ["SoundDeviceBackend", "audio_device_count"]
