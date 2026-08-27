"""Product-owned adapter for the Rhasspy pyopen-wakeword streaming flow.

The small trigger/refractory loop follows the Apache-2.0 licensed
``wyoming-openwakeword`` reference implementation.  BMO deliberately keeps
the reference detector in-process: Wyoming networking is not part of the
voice architecture.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
from personal_ai_os.voice.contracts import AudioFrame, WakeWordDetector

SAMPLE_RATE_HZ = 16_000
SAMPLES_PER_WAKE_CHUNK = 160
BYTES_PER_WAKE_CHUNK = SAMPLES_PER_WAKE_CHUNK * 2
DEFAULT_THRESHOLD = 0.5
DEFAULT_TRIGGER_LEVEL = 1
DEFAULT_REFRACTORY_SECONDS = 2.0
PYOPEN_WAKEWORD_VERSION = "1.1.0"
PYOPEN_WAKEWORD_REPOSITORY = "https://github.com/rhasspy/pyopen-wakeword"
PYOPEN_WAKEWORD_COMMIT = "6bc5c5f5c9c71e46a723b6c9277b1d50f2ba13fd"
WYOMING_OPENWAKEWORD_REPOSITORY = "https://github.com/rhasspy/wyoming-openwakeword"
WYOMING_OPENWAKEWORD_COMMIT = "419701f64aa936ff62a820dfeac757f1afda01d1"
HEY_JARVIS_MODEL_FILENAME = "hey_jarvis.tflite"
HEY_JARVIS_MODEL_SHA256 = "14bff778604985e1b5c19f0f7bbe477a69cf281d8db34b232b3b972411f710e2"


class _StreamingFeatures(Protocol):
    def process_streaming(self, audio_chunk: bytes) -> Iterable[Any]: ...

    def reset(self) -> None: ...


class _StreamingWake(Protocol):
    def process_streaming(self, embeddings: Any) -> Iterable[float]: ...

    def reset(self) -> None: ...


def split_pcm16_chunks(pcm_s16le: bytes) -> tuple[tuple[bytes, ...], bytes]:
    """Return complete 10 ms chunks and the unconsumed byte residual.

    The tuple contains ``(chunks, residual)`` so callers can preserve every
    byte when a capture frame is not an exact multiple of 10 ms.
    """

    complete_bytes = len(pcm_s16le) - (len(pcm_s16le) % BYTES_PER_WAKE_CHUNK)
    chunks = tuple(
        pcm_s16le[offset : offset + BYTES_PER_WAKE_CHUNK]
        for offset in range(0, complete_bytes, BYTES_PER_WAKE_CHUNK)
    )
    return chunks, pcm_s16le[complete_bytes:]


class RhasspyHeyJarvisDetector(WakeWordDetector):
    """Persistent 16 kHz PCM16 detector using the built-in Hey Jarvis model."""

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        trigger_level: int = DEFAULT_TRIGGER_LEVEL,
        refractory_seconds: float = DEFAULT_REFRACTORY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        probability_observer: Callable[[float], None] | None = None,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("wake threshold must be between 0 and 1")
        if trigger_level < 1:
            raise ValueError("wake trigger level must be positive")
        if refractory_seconds < 0:
            raise ValueError("wake refractory must not be negative")

        try:
            module = importlib.import_module("pyopen_wakeword")
            model = module.Model.HEY_JARVIS
            features = module.OpenWakeWordFeatures.from_builtin()
            wake = module.OpenWakeWord.from_builtin(model)
        except (ImportError, OSError, RuntimeError, AttributeError, TypeError) as exc:
            raise VoiceDependencyUnavailable(
                "pyopen-wakeword Hey Jarvis runtime is unavailable"
            ) from exc

        self._features: _StreamingFeatures = features
        self._wake: _StreamingWake = wake
        self._clock = clock
        self.threshold = threshold
        self.trigger_level = trigger_level
        self.refractory_seconds = refractory_seconds
        self._probability_observer = probability_observer
        self._triggers_left = trigger_level
        self._last_triggered: float | None = None
        self._residual = bytearray()
        self._last_probability = 0.0
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    @property
    def last_probability(self) -> float:
        return self._last_probability

    @property
    def residual_bytes(self) -> bytes:
        """Expose only the bounded residual size/content for deterministic tests."""

        return bytes(self._residual)

    def _probabilities(self, chunk: bytes) -> Iterable[float]:
        for embedding in self._features.process_streaming(chunk):
            yield from self._wake.process_streaming(embedding)

    def detected(self, frame: AudioFrame) -> bool:
        """Advance streaming state and report at most one wake for this frame."""

        if not self._available:
            return False
        if frame.sample_rate_hz != SAMPLE_RATE_HZ or frame.channels != 1:
            raise ValueError("wake detector requires 16 kHz mono PCM16")

        self._residual.extend(frame.pcm_s16le)
        chunks, residual = split_pcm16_chunks(bytes(self._residual))
        self._residual = bytearray(residual)
        triggered = False
        try:
            for chunk in chunks:
                for probability in self._probabilities(chunk):
                    self._last_probability = float(probability)
                    if self._probability_observer is not None:
                        self._probability_observer(self._last_probability)
                    now = self._clock()
                    if (
                        self._last_triggered is not None
                        and now - self._last_triggered < self.refractory_seconds
                    ):
                        continue
                    if self._last_probability <= self.threshold:
                        continue
                    self._triggers_left -= 1
                    if self._triggers_left <= 0:
                        self._last_triggered = now
                        self._triggers_left = self.trigger_level
                        triggered = True
        except (OSError, RuntimeError, TypeError, ValueError):
            # A broken optional wake runtime must never activate the assistant.
            self._available = False
            return False
        return triggered

    def reset(self) -> None:
        """Reset both upstream streaming state and BMO detector state."""

        for component in (self._features, self._wake):
            reset = getattr(component, "reset", None)
            if callable(reset):
                reset()
        self._triggers_left = self.trigger_level
        self._last_triggered = None
        self._residual.clear()
        self._last_probability = 0.0
        self._available = True

    def close(self) -> None:
        """Release upstream runtime resources without retaining audio."""

        for component in (self._features, self._wake):
            close = getattr(component, "close", None)
            if callable(close):
                close()
        self._available = False


__all__ = [
    "BYTES_PER_WAKE_CHUNK",
    "DEFAULT_REFRACTORY_SECONDS",
    "DEFAULT_THRESHOLD",
    "DEFAULT_TRIGGER_LEVEL",
    "HEY_JARVIS_MODEL_FILENAME",
    "HEY_JARVIS_MODEL_SHA256",
    "PYOPEN_WAKEWORD_COMMIT",
    "PYOPEN_WAKEWORD_REPOSITORY",
    "PYOPEN_WAKEWORD_VERSION",
    "SAMPLES_PER_WAKE_CHUNK",
    "SAMPLE_RATE_HZ",
    "WYOMING_OPENWAKEWORD_COMMIT",
    "WYOMING_OPENWAKEWORD_REPOSITORY",
    "RhasspyHeyJarvisDetector",
    "split_pcm16_chunks",
]
