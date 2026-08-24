"""Optional Windows capture/playback backend with memory-only audio handling."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Sequence
from typing import Any

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
from personal_ai_os.voice.contracts import AudioFrame


class SoundDeviceBackend:
    """Use the local default microphone and speaker without writing audio files."""

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16_000,
        input_device: int | str | None = None,
        output_device: int | str | None = None,
    ) -> None:
        try:
            self._sounddevice: Any = importlib.import_module("sounddevice")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("sounddevice is not installed") from exc
        self.sample_rate_hz = sample_rate_hz
        self.input_device = input_device
        self.output_device = output_device
        try:
            input_info = self._sounddevice.query_devices(input_device, "input")
            output_info = self._sounddevice.query_devices(output_device, "output")
        except (OSError, ValueError, TypeError) as exc:
            raise VoiceDependencyUnavailable("selected audio device is unavailable") from exc
        if int(input_info.get("max_input_channels", 0)) < 1:
            raise VoiceDependencyUnavailable("selected microphone has no input channel")
        if int(output_info.get("max_output_channels", 0)) < 1:
            raise VoiceDependencyUnavailable("selected playback device has no output channel")
        self.input_device_name = str(input_info.get("name", "unnamed microphone"))
        self.output_device_name = str(output_info.get("name", "unnamed playback device"))
        self._output_lock = threading.Lock()
        self._output_stream: Any | None = None

    def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
        """Capture one bounded in-memory utterance from the default input device."""

        if not 0 < seconds <= 20:
            raise ValueError("capture duration is outside the bounded limit")
        raw_chunks = bytearray()

        def callback(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
            raw_chunks.extend(bytes(indata))

        stream = self._sounddevice.RawInputStream(
            samplerate=self.sample_rate_hz,
            channels=1,
            dtype="int16",
            device=self.input_device,
            callback=callback,
        )
        started = False
        try:
            stream.start()
            started = True
            time.sleep(seconds)
        finally:
            if started:
                stream.stop()
            stream.close()

        raw = bytes(raw_chunks)
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
        cursor = 0

        def callback(outdata: Any, frame_count: int, _time_info: Any, _status: Any) -> None:
            nonlocal cursor
            del frame_count
            output_bytes = len(outdata)
            chunk = samples[cursor : cursor + output_bytes]
            cursor += len(chunk)
            if len(chunk) < output_bytes:
                chunk += b"\x00" * (output_bytes - len(chunk))
            outdata[:output_bytes] = chunk
            if cursor >= len(samples):
                raise self._sounddevice.CallbackStop()

        stream = self._sounddevice.RawOutputStream(
            samplerate=frames[0].sample_rate_hz,
            channels=1,
            dtype="int16",
            device=self.output_device,
            callback=callback,
        )
        with self._output_lock:
            self._output_stream = stream
        started = False
        try:
            stream.start()
            started = True
            deadline = time.monotonic() + 15.0
            while stream.active and time.monotonic() < deadline:
                time.sleep(0.01)
            if stream.active:
                raise TimeoutError("playback stream did not complete within 15 seconds")
        finally:
            if started:
                stream.stop()
            stream.close()
            with self._output_lock:
                if self._output_stream is stream:
                    self._output_stream = None

    def stop(self) -> None:
        """Stop only the local voice playback stream."""

        with self._output_lock:
            stream = self._output_stream
        if stream is None:
            return
        try:
            stream.abort()
        except (OSError, RuntimeError):
            stream.stop()


def audio_device_count() -> int:
    """Return a scalar device count for sanitized diagnostics."""

    try:
        module: Any = importlib.import_module("sounddevice")
        return len(module.query_devices())
    except (ImportError, OSError):
        return 0


__all__ = ["SoundDeviceBackend", "audio_device_count"]
