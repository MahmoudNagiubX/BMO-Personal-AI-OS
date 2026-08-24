"""Safe response presentation and cancellable phrase-level local TTS."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from time import perf_counter

from personal_ai_os.voice.contracts import AudioFrame, AudioPlayback, SpeechSynthesizer


@dataclass(frozen=True, slots=True)
class TtsStreamMetrics:
    """Scalar response-presentation measurements; no audio is retained."""

    chunk_count: int
    first_audio_latency_ms: float | None
    cancelled: bool


class VoicePresentationPolicy:
    """Convert text into bounded speakable chunks without changing its facts."""

    def __init__(self, *, max_chunk_characters: int = 240) -> None:
        if max_chunk_characters < 32:
            raise ValueError("voice phrase chunks are too small")
        self.max_chunk_characters = max_chunk_characters

    def speakable(self, text: str) -> str:
        """Remove display-only markdown markers while preserving visible content."""

        normalized = text.replace("```", " ").replace("**", "").replace("__", "")
        normalized = re.sub(r"^\s*[-*+]\s+", "", normalized, flags=re.MULTILINE)
        normalized = normalized.replace("`", "")
        return " ".join(normalized.split())

    def chunks(self, text: str) -> Iterator[str]:
        normalized = self.speakable(text)
        if not normalized:
            return
        # Keep URLs, code-like payloads, and approval text intact as one unit.
        if any(marker in normalized for marker in ("http://", "https://", "approval", "approve")):
            yield normalized
            return
        parts = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", normalized)
        pending = ""
        for part in parts:
            if not part:
                continue
            candidate = f"{pending} {part}".strip()
            if pending and len(candidate) > self.max_chunk_characters:
                yield pending
                pending = part
            else:
                pending = candidate
        if pending:
            while len(pending) > self.max_chunk_characters:
                split_at = pending.rfind(" ", 0, self.max_chunk_characters + 1)
                if split_at <= 0:
                    split_at = self.max_chunk_characters
                yield pending[:split_at].strip()
                pending = pending[split_at:].strip()
            if pending:
                yield pending


class CancellableTtsStream:
    """Generate and play bounded chunks in order, with true interruption."""

    def __init__(
        self,
        *,
        synthesizer: SpeechSynthesizer,
        playback: AudioPlayback,
        policy: VoicePresentationPolicy | None = None,
        max_queue_chunks: int = 4,
    ) -> None:
        if max_queue_chunks <= 0:
            raise ValueError("TTS queue bound must be positive")
        self.synthesizer = synthesizer
        self.playback = playback
        self.policy = policy or VoicePresentationPolicy()
        self.max_queue_chunks = max_queue_chunks
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.last_metrics = TtsStreamMetrics(0, None, False)

    def speak(self, text: str) -> bool:
        """Speak safe chunks; return false when local TTS/playback degrades."""

        # Process chunks sequentially.  The bound describes the maximum amount
        # of response work that may be queued by a caller; it must never cause
        # a truthful assistant response to be silently truncated.  A future
        # asynchronous producer may enforce the same bound by applying
        # backpressure before calling this method.
        chunks = list(self.policy.chunks(text))
        self._cancel.clear()
        started = perf_counter()
        first_audio_ms: float | None = None
        played = 0
        try:
            for chunk in chunks:
                if self._cancel.is_set():
                    break
                frames: Sequence[AudioFrame] = self.synthesizer.synthesize(chunk)
                if self._cancel.is_set():
                    break
                self.playback.play(frames)
                played += 1
                if first_audio_ms is None:
                    first_audio_ms = (perf_counter() - started) * 1000
        except Exception:
            self.last_metrics = TtsStreamMetrics(played, first_audio_ms, self._cancel.is_set())
            return False
        self.last_metrics = TtsStreamMetrics(played, first_audio_ms, self._cancel.is_set())
        return not self._cancel.is_set()

    def cancel(self) -> None:
        """Stop local playback and cancel queued/future phrase synthesis."""

        with self._lock:
            self._cancel.set()
            self.playback.stop()


__all__ = ["CancellableTtsStream", "TtsStreamMetrics", "VoicePresentationPolicy"]
