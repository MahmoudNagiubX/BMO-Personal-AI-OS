"""Optional Windows capture/playback backend with memory-only audio handling."""

from __future__ import annotations

import importlib
import threading
import time
from array import array
from collections.abc import Callable, Sequence
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
        self._playback_reference: bytes | None = None

    def stream_input(
        self,
        callback: Callable[[AudioFrame], None],
        *,
        seconds: float,
        stop_event: threading.Event | None = None,
        frame_duration_seconds: float = 0.08,
    ) -> None:
        """Deliver bounded live PCM frames to ``callback`` without persistence.

        The method is intentionally blocking so callers can own its lifetime
        in one bounded worker thread.  ``stop_event`` provides prompt,
        deterministic shutdown for interruption and owner abort paths.
        """

        if not 0 < seconds <= 60:
            raise ValueError("stream duration is outside the bounded limit")
        if not 0.04 <= frame_duration_seconds <= 0.2:
            raise ValueError("stream frame duration is outside the bounded limit")
        frame_bytes = int(self.sample_rate_hz * frame_duration_seconds) * 2
        if frame_bytes <= 0:
            raise ValueError("stream frame size must be positive")

        local_stop = threading.Event()
        raw_buffer = bytearray()
        callback_errors: list[Exception] = []

        def input_callback(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
            try:
                raw_buffer.extend(bytes(indata))
                while len(raw_buffer) >= frame_bytes:
                    pcm = bytes(raw_buffer[:frame_bytes])
                    del raw_buffer[:frame_bytes]
                    callback(AudioFrame(pcm, sample_rate_hz=self.sample_rate_hz))
            except Exception as exc:
                callback_errors.append(exc)
                local_stop.set()

        stream = self._sounddevice.RawInputStream(
            samplerate=self.sample_rate_hz,
            channels=1,
            dtype="int16",
            device=self.input_device,
            callback=input_callback,
        )
        started = False
        deadline = time.monotonic() + seconds
        try:
            stream.start()
            started = True
            while time.monotonic() < deadline and not local_stop.is_set():
                if stop_event is not None and stop_event.wait(0.02):
                    break
                if stop_event is None:
                    time.sleep(0.02)
        finally:
            if started:
                stream.stop()
            stream.close()
        if callback_errors:
            raise callback_errors[0]

    def capture(self, *, seconds: float) -> tuple[AudioFrame, ...]:
        """Capture one bounded in-memory utterance from the default input device."""

        frames: list[AudioFrame] = []
        self.stream_input(frames.append, seconds=seconds)
        return tuple(frames)

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
            with self._output_lock:
                self._playback_reference = bytes(chunk)
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
                self._playback_reference = None

    def is_playback_echo(self, frame: AudioFrame) -> bool:
        """Identify a high-correlation playback-only frame in memory.

        This is a conservative deterministic guard for synthetic/direct-loop
        leakage.  It never writes audio and returns false when no current
        playback reference is available, preserving real owner barge-in.
        """

        with self._output_lock:
            reference = self._playback_reference
        if reference is None or len(reference) != len(frame.pcm_s16le):
            return False
        samples = array("h", frame.pcm_s16le)
        reference_samples = array("h", reference)
        if not samples or not reference_samples:
            return False
        frame_energy = sum(sample * sample for sample in samples)
        reference_energy = sum(sample * sample for sample in reference_samples)
        if frame_energy == 0 or reference_energy == 0:
            return False
        correlation = sum(
            sample * reference_sample
            for sample, reference_sample in zip(samples, reference_samples, strict=True)
        )
        return (correlation * correlation) >= int(frame_energy * reference_energy * 0.92**2)

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
