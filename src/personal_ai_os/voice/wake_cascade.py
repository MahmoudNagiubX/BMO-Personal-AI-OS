"""Two-stage local wake-candidate and phrase-verification boundaries.

The first stage is intentionally allowed to favor recall.  The verifier owns
the final linguistic decision and only accepts an exact ``Jarvis`` token at
the beginning of the transient transcript.  Neither class persists audio or
routes a request around the authenticated Core pipeline.
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from personal_ai_os.voice.contracts import (
    AudioFrame,
    SpeechRecognizer,
    VoiceActivityDetector,
    WakeWordDetector,
)

_NON_WORD = re.compile(r"[^\w']+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class WakeVerification:
    """Sanitized verifier output; transcript text never leaves the adapter."""

    accepted: bool
    normalized_word_count: int
    wake_token_at_start: bool
    latency_ms: float


class WakeCandidateVerifier(Protocol):
    """Final local wake decision over a bounded in-memory candidate window."""

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification: ...


def normalize_wake_text(text: str) -> tuple[str, ...]:
    """Normalize punctuation/case without adding fuzzy aliases."""

    return tuple(token for token in _NON_WORD.sub(" ", text.casefold()).split() if token)


def starts_with_exact_wake_word(text: str, wake_word: str = "Jarvis") -> bool:
    """Accept the exact wake token followed by optional command text."""

    tokens = normalize_wake_text(text)
    expected = normalize_wake_text(wake_word)
    return bool(expected) and tokens[: len(expected)] == expected


class WhisperWakePhraseVerifier:
    """Use an existing local recognizer only after a candidate is raised."""

    def __init__(self, recognizer: SpeechRecognizer, *, wake_word: str = "Jarvis") -> None:
        if not wake_word.strip():
            raise ValueError("wake word is required")
        self._recognizer = recognizer
        self.wake_word = wake_word

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification:
        if not frames:
            raise ValueError("wake verification requires a bounded audio window")
        started = time.perf_counter()
        transcript = self._recognizer.transcribe(frames)
        tokens = normalize_wake_text(transcript)
        expected = normalize_wake_text(self.wake_word)
        at_start = bool(expected) and tokens[: len(expected)] == expected
        return WakeVerification(
            accepted=at_start,
            normalized_word_count=len(tokens),
            wake_token_at_start=at_start,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


class WakeCascadeDetector:
    """Candidate detector followed by a local exact-prefix Whisper verifier."""

    def __init__(
        self,
        *,
        candidate: WakeWordDetector,
        verifier: WakeCandidateVerifier,
        vad: VoiceActivityDetector | None = None,
        speech_gate: Callable[[AudioFrame], bool] | None = None,
        sample_rate_hz: int = 16_000,
        max_candidate_seconds: float = 4.0,
    ) -> None:
        if sample_rate_hz <= 0 or max_candidate_seconds <= 0:
            raise ValueError("wake cascade bounds must be positive")
        if vad is not None and speech_gate is not None:
            raise ValueError("choose either a VAD or scalar speech gate")
        self._candidate = candidate
        self._verifier = verifier
        self._vad = vad
        self._speech_gate = speech_gate
        self._sample_rate_hz = sample_rate_hz
        self._max_candidate_bytes = int(max_candidate_seconds * sample_rate_hz) * 2
        self._frames: deque[AudioFrame] = deque()
        self.last_verification: WakeVerification | None = None

    @property
    def available(self) -> bool:
        return self._candidate.available

    def detected(self, frame: AudioFrame) -> bool:
        if frame.sample_rate_hz != self._sample_rate_hz or frame.channels != 1:
            raise ValueError("wake cascade frame format is unsupported")
        self._frames.append(frame)
        self._trim()
        if not self._speech_present(frame):
            return False
        if not self._candidate.detected(frame):
            return False
        result = self._verifier.verify(tuple(self._frames))
        self.last_verification = result
        self._reset_detector()
        return result.accepted

    def reset(self) -> None:
        self._reset_detector()

    def _speech_present(self, frame: AudioFrame) -> bool:
        if self._speech_gate is not None:
            return bool(self._speech_gate(frame))
        if self._vad is not None:
            return bool(self._vad.contains_speech((frame,)))
        return True

    def _trim(self) -> None:
        total = sum(len(frame.pcm_s16le) for frame in self._frames)
        while self._frames and total > self._max_candidate_bytes:
            total -= len(self._frames.popleft().pcm_s16le)

    def _reset_detector(self) -> None:
        reset = getattr(self._candidate, "reset", None)
        if callable(reset):
            reset()
        self._frames.clear()


__all__ = [
    "WakeCandidateVerifier",
    "WakeCascadeDetector",
    "WakeVerification",
    "WhisperWakePhraseVerifier",
    "normalize_wake_text",
    "starts_with_exact_wake_word",
]
