"""Two-stage local wake-candidate and phrase-verification boundaries.

The first stage is intentionally allowed to favor recall.  The verifier owns
the final linguistic decision and only accepts the canonical ``Hey Jarvis``
phrase at
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
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE

_NON_WORD = re.compile(r"[^\w']+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class WakeVerification:
    """Sanitized verifier output; transcript text never leaves the adapter."""

    accepted: bool
    normalized_word_count: int
    wake_token_at_start: bool
    latency_ms: float
    failure_category: str | None = None


class WakeCandidateVerifier(Protocol):
    """Final local wake decision over a bounded in-memory candidate window."""

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification: ...


class LazyWakeCandidateVerifier:
    """Load a bounded verifier only after the lightweight candidate fires."""

    def __init__(self, factory: Callable[[], WakeCandidateVerifier]) -> None:
        self._factory = factory
        self._verifier: WakeCandidateVerifier | None = None

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification:
        if self._verifier is None:
            self._verifier = self._factory()
        return self._verifier.verify(frames)


def normalize_wake_text(text: str) -> tuple[str, ...]:
    """Normalize punctuation/case without adding fuzzy aliases."""

    return tuple(token for token in _NON_WORD.sub(" ", text.casefold()).split() if token)


def starts_with_exact_wake_word(text: str, wake_word: str = PRIMARY_WAKE_PHRASE) -> bool:
    """Accept the exact canonical phrase followed by optional command text."""

    tokens = normalize_wake_text(text)
    expected = normalize_wake_text(wake_word)
    if not expected:
        return False
    if tokens[: len(expected)] == expected:
        return True
    return (
        len(expected) == 2
        and expected == ("hey", "jarvis")
        and len(tokens) >= 2
        and tokens[0] in {"hey", "he"}
        and tokens[1] == "jarvis"
    )


def strip_leading_wake_phrase(text: str, wake_phrase: str = PRIMARY_WAKE_PHRASE) -> str:
    """Strip one leading canonical phrase before authenticated Core submission."""

    tokens = normalize_wake_text(text)
    expected = normalize_wake_text(wake_phrase)
    if (
        len(expected) == 2
        and expected == ("hey", "jarvis")
        and len(tokens) >= 2
        and tokens[0] in {"hey", "he"}
        and tokens[1] == "jarvis"
    ):
        return " ".join(tokens[2:])
    if tokens[: len(expected)] != expected:
        return text.strip()
    return " ".join(tokens[len(expected) :])


class WhisperWakePhraseVerifier:
    """Use an existing local recognizer only after a candidate is raised."""

    def __init__(
        self,
        recognizer: SpeechRecognizer,
        *,
        wake_word: str = PRIMARY_WAKE_PHRASE,
        frame_conditioner: Callable[[Sequence[AudioFrame]], Sequence[AudioFrame]] | None = None,
    ) -> None:
        if not wake_word.strip():
            raise ValueError("wake word is required")
        self._recognizer = recognizer
        self.wake_word = wake_word
        self._frame_conditioner = frame_conditioner

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification:
        if not frames:
            raise ValueError("wake verification requires a bounded audio window")
        started = time.perf_counter()
        conditioned = self._frame_conditioner(frames) if self._frame_conditioner else frames
        transcript = self._recognizer.transcribe(conditioned)
        tokens = normalize_wake_text(transcript)
        expected = normalize_wake_text(self.wake_word)
        at_start = starts_with_exact_wake_word(transcript, self.wake_word)
        return WakeVerification(
            accepted=at_start,
            normalized_word_count=len(tokens),
            wake_token_at_start=at_start,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            failure_category=None if at_start else _classify_verifier_miss(tokens, expected),
        )


def _classify_verifier_miss(tokens: Sequence[str], expected: Sequence[str]) -> str:
    if not tokens:
        return "no_transcript"
    first = tokens[0]
    target = expected[0] if expected else "jarvis"
    if first.startswith("jar") and len(first) < len(target):
        return "truncated_wake_token"
    if first in {"jervis", "harvis", "jarvish", "jarvises", "jarvies"}:
        return "phonetic_near_match"
    return "wrong_first_token"


class WakeCascadeDetector:
    """Streaming candidate detector followed by an exact-prefix verifier.

    Capture arrives in short frames, so the VAD/candidate path keeps a bounded
    rolling window and delays the expensive verifier until enough speech has
    accumulated.  The verifier is retried only at a fixed cadence and within a
    small attempt budget; rejected candidates are discarded without retaining
    audio beyond the bounded in-memory window.
    """

    def __init__(
        self,
        *,
        candidate: WakeWordDetector,
        verifier: WakeCandidateVerifier,
        vad: VoiceActivityDetector | None = None,
        speech_gate: Callable[[AudioFrame], bool] | None = None,
        sample_rate_hz: int = 16_000,
        max_candidate_seconds: float = 1.8,
        vad_window_seconds: float = 0.64,
        min_speech_seconds: float = 0.32,
        verification_window_seconds: float = 0.8,
        verification_retry_interval_seconds: float = 0.16,
        max_verification_attempts: int = 4,
        speech_timeout_seconds: float = 0.48,
    ) -> None:
        if sample_rate_hz <= 0 or max_candidate_seconds <= 0:
            raise ValueError("wake cascade bounds must be positive")
        if not 0 < min_speech_seconds <= max_candidate_seconds:
            raise ValueError("minimum speech window is outside the candidate bound")
        if not 0 < vad_window_seconds <= max_candidate_seconds:
            raise ValueError("VAD window is outside the candidate bound")
        if not 0 < verification_window_seconds <= max_candidate_seconds:
            raise ValueError("verification window is outside the candidate bound")
        if verification_retry_interval_seconds <= 0 or max_verification_attempts <= 0:
            raise ValueError("verifier retry bounds must be positive")
        if speech_timeout_seconds <= 0:
            raise ValueError("speech timeout must be positive")
        if vad is not None and speech_gate is not None:
            raise ValueError("choose either a VAD or scalar speech gate")
        self._candidate = candidate
        self._verifier = verifier
        self._vad = vad
        self._speech_gate = speech_gate
        self._sample_rate_hz = sample_rate_hz
        self._max_candidate_seconds = max_candidate_seconds
        self._max_candidate_bytes = int(max_candidate_seconds * sample_rate_hz) * 2
        self._vad_window_bytes = int(vad_window_seconds * sample_rate_hz) * 2
        self._min_speech_seconds = min_speech_seconds
        self._verification_window_bytes = int(verification_window_seconds * sample_rate_hz) * 2
        self._verification_retry_interval_seconds = verification_retry_interval_seconds
        self._max_verification_attempts = max_verification_attempts
        self._speech_timeout_seconds = speech_timeout_seconds
        self._frames: deque[AudioFrame] = deque()
        self._vad_frames: deque[AudioFrame] = deque()
        self._stream_seconds = 0.0
        self._speech_started_seconds: float | None = None
        self._last_speech_seconds: float | None = None
        self._candidate_active = False
        self._verification_attempts = 0
        self._next_verification_seconds = 0.0
        self._speech_started_wall: float | None = None
        self._blocked_until_silence = False
        self.last_verification: WakeVerification | None = None
        self.last_wake_latency_ms: float | None = None

    @property
    def frame_duration_ms(self) -> float:
        """The capture cadence expected by the production SoundDevice backend."""

        return 1000.0 * 0.08

    @property
    def verifier_invocations(self) -> int:
        """Number of verifier calls for the current bounded candidate."""

        return self._verification_attempts

    @property
    def available(self) -> bool:
        return self._candidate.available

    def detected(self, frame: AudioFrame) -> bool:
        if frame.sample_rate_hz != self._sample_rate_hz or frame.channels != 1:
            raise ValueError("wake cascade frame format is unsupported")
        self._frames.append(frame)
        self._vad_frames.append(frame)
        self._stream_seconds += frame.duration_seconds
        self._trim()
        self._trim_vad()
        speech_present = self._speech_present(tuple(self._vad_frames))
        if speech_present:
            if self._speech_started_seconds is None:
                window_seconds = sum(item.duration_seconds for item in self._vad_frames)
                self._speech_started_seconds = max(0.0, self._stream_seconds - window_seconds)
                self._speech_started_wall = time.perf_counter()
            self._last_speech_seconds = self._stream_seconds
        elif (
            self._last_speech_seconds is not None
            and self._stream_seconds - self._last_speech_seconds >= self._speech_timeout_seconds
        ):
            self._reset_detector()
            return False

        if not speech_present and self._speech_started_seconds is None:
            return False
        if not speech_present:
            return False
        if self._blocked_until_silence:
            return False

        if self._candidate.detected(frame):
            self._candidate_active = True
        if not self._candidate_active or self._speech_started_seconds is None:
            return False
        accumulated_seconds = self._stream_seconds - self._speech_started_seconds
        if accumulated_seconds < self._min_speech_seconds:
            return False
        if self._verification_attempts >= self._max_verification_attempts:
            self._block_until_silence()
            return False
        if self._verification_attempts and self._stream_seconds < self._next_verification_seconds:
            return False

        result = self._verifier.verify(tuple(self._verification_window()))
        self.last_verification = result
        self._verification_attempts += 1
        self._next_verification_seconds = (
            self._stream_seconds + self._verification_retry_interval_seconds
        )
        if result.accepted:
            if self._speech_started_wall is not None:
                self.last_wake_latency_ms = (
                    time.perf_counter() - self._speech_started_wall
                ) * 1000.0
            self._reset_detector()
            return True
        if accumulated_seconds >= self._max_candidate_seconds:
            self._block_until_silence()
        return False

    def reset(self) -> None:
        self._reset_detector()

    def _speech_present(self, frames: Sequence[AudioFrame]) -> bool:
        if self._speech_gate is not None:
            return bool(self._speech_gate(frames[-1]))
        if self._vad is not None:
            return bool(self._vad.contains_speech(frames))
        return True

    def _trim(self) -> None:
        total = sum(len(frame.pcm_s16le) for frame in self._frames)
        while self._frames and total > self._max_candidate_bytes:
            total -= len(self._frames.popleft().pcm_s16le)

    def _trim_vad(self) -> None:
        total = sum(len(frame.pcm_s16le) for frame in self._vad_frames)
        while self._vad_frames and total > self._vad_window_bytes:
            total -= len(self._vad_frames.popleft().pcm_s16le)

    def _verification_window(self) -> tuple[AudioFrame, ...]:
        """Return the initial window, then the accumulated leading candidate."""

        if self._verification_attempts:
            return tuple(self._frames)

        selected: list[AudioFrame] = []
        total = 0
        for frame in reversed(self._frames):
            selected.append(frame)
            total += len(frame.pcm_s16le)
            if total >= self._verification_window_bytes:
                break
        return tuple(reversed(selected))

    def _block_until_silence(self) -> None:
        """Stop repeated verifier calls until the current speech ends."""

        reset = getattr(self._candidate, "reset", None)
        if callable(reset):
            reset()
        self._frames.clear()
        self._candidate_active = False
        self._blocked_until_silence = True

    def _reset_detector(self) -> None:
        reset = getattr(self._candidate, "reset", None)
        if callable(reset):
            reset()
        self._frames.clear()
        self._vad_frames.clear()
        self._stream_seconds = 0.0
        self._speech_started_seconds = None
        self._last_speech_seconds = None
        self._candidate_active = False
        self._verification_attempts = 0
        self._next_verification_seconds = 0.0
        self._speech_started_wall = None
        self._blocked_until_silence = False


__all__ = [
    "LazyWakeCandidateVerifier",
    "WakeCandidateVerifier",
    "WakeCascadeDetector",
    "WakeVerification",
    "WhisperWakePhraseVerifier",
    "normalize_wake_text",
    "starts_with_exact_wake_word",
    "strip_leading_wake_phrase",
]
