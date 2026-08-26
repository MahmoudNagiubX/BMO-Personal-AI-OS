"""Speech-gated local ASR wake detection.

The detector deliberately has no cheap wake classifier before ASR.  Silero
only identifies a bounded speech candidate; the existing English wake ASR
then makes the exact-prefix decision.  Audio remains in bounded process
memory and is cleared after every candidate.
"""

from __future__ import annotations

from collections import deque

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
from personal_ai_os.voice.contracts import AudioFrame, VoiceActivityDetector, WakeWordDetector
from personal_ai_os.voice.wake_cascade import (
    WakeCandidateVerifier,
    WakeVerification,
)

SAMPLE_RATE_HZ = 16_000
DEFAULT_MAX_CANDIDATE_SECONDS = 1.8
DEFAULT_VAD_WINDOW_SECONDS = 0.64
DEFAULT_MIN_SPEECH_SECONDS = 0.32
DEFAULT_INITIAL_VERIFICATION_SECONDS = 0.32
DEFAULT_RETRY_INTERVAL_SECONDS = 0.16
DEFAULT_MAX_VERIFICATION_ATTEMPTS = 4
DEFAULT_SPEECH_END_SILENCE_SECONDS = 0.48


class SpeechGatedHeyJarvisDetector(WakeWordDetector):
    """Use VAD as a speech gate and bounded faster-whisper as the wake decision."""

    def __init__(
        self,
        *,
        vad: VoiceActivityDetector,
        verifier: WakeCandidateVerifier,
        sample_rate_hz: int = SAMPLE_RATE_HZ,
        max_candidate_seconds: float = DEFAULT_MAX_CANDIDATE_SECONDS,
        vad_window_seconds: float = DEFAULT_VAD_WINDOW_SECONDS,
        min_speech_seconds: float = DEFAULT_MIN_SPEECH_SECONDS,
        initial_verification_seconds: float = DEFAULT_INITIAL_VERIFICATION_SECONDS,
        retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS,
        max_verification_attempts: int = DEFAULT_MAX_VERIFICATION_ATTEMPTS,
        speech_end_silence_seconds: float = DEFAULT_SPEECH_END_SILENCE_SECONDS,
    ) -> None:
        if sample_rate_hz <= 0:
            raise ValueError("speech-gated wake sample rate must be positive")
        if max_candidate_seconds <= 0 or vad_window_seconds <= 0:
            raise ValueError("speech-gated wake windows must be positive")
        if vad_window_seconds > max_candidate_seconds:
            raise ValueError("VAD window cannot exceed candidate window")
        if not 0 < min_speech_seconds <= max_candidate_seconds:
            raise ValueError("minimum speech window is outside the candidate bound")
        if not min_speech_seconds <= initial_verification_seconds <= max_candidate_seconds:
            raise ValueError("initial verification window is outside the candidate bound")
        if retry_interval_seconds <= 0 or max_verification_attempts <= 0:
            raise ValueError("wake verification retry bounds must be positive")
        if speech_end_silence_seconds <= 0:
            raise ValueError("speech-end silence bound must be positive")

        self._vad = vad
        self._verifier = verifier
        self._sample_rate_hz = sample_rate_hz
        self._max_candidate_seconds = max_candidate_seconds
        self._max_candidate_bytes = int(max_candidate_seconds * sample_rate_hz) * 2
        self._vad_window_bytes = int(vad_window_seconds * sample_rate_hz) * 2
        self._min_speech_seconds = min_speech_seconds
        self._initial_verification_seconds = initial_verification_seconds
        self._retry_interval_seconds = retry_interval_seconds
        self._max_verification_attempts = max_verification_attempts
        self._speech_end_silence_seconds = speech_end_silence_seconds
        self._frames: deque[AudioFrame] = deque()
        self._vad_frames: deque[AudioFrame] = deque()
        self._stream_seconds = 0.0
        self._candidate_seconds = 0.0
        self._silence_seconds = 0.0
        self._candidate_active = False
        self._blocked_until_silence = False
        self._verification_attempts = 0
        self._next_verification_seconds = 0.0
        self._available = True
        self.last_verification: WakeVerification | None = None
        self.last_failure_category: str | None = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def verifier_invocations(self) -> int:
        """Number of bounded ASR calls for the current candidate."""

        return self._verification_attempts

    @property
    def candidate_active(self) -> bool:
        return self._candidate_active

    @property
    def buffered_bytes(self) -> int:
        """Expose only bounded size for diagnostics; audio bytes never leave the adapter."""

        return sum(len(frame.pcm_s16le) for frame in self._frames)

    def detected(self, frame: AudioFrame) -> bool:
        if not self._available:
            return False
        if frame.sample_rate_hz != self._sample_rate_hz or frame.channels != 1:
            raise ValueError("speech-gated wake requires 16 kHz mono PCM16")

        self._frames.append(frame)
        self._vad_frames.append(frame)
        self._stream_seconds += frame.duration_seconds
        self._trim(self._frames, self._max_candidate_bytes)
        self._trim(self._vad_frames, self._vad_window_bytes)

        try:
            speech_present = bool(self._vad.contains_speech(tuple(self._vad_frames)))
        except (OSError, RuntimeError, TypeError, ValueError, VoiceDependencyUnavailable) as exc:
            self._fail_closed("vad_unavailable", exc)
            return False

        if not speech_present:
            if self._candidate_active:
                self._silence_seconds += frame.duration_seconds
                if self._silence_seconds >= self._speech_end_silence_seconds:
                    self._clear_candidate()
                    self._vad_frames.clear()
            elif self._blocked_until_silence:
                self._blocked_until_silence = False
                self._vad_frames.clear()
            return False

        if self._blocked_until_silence:
            return False
        if not self._candidate_active:
            self._candidate_active = True
            self._candidate_seconds = 0.0
            self._silence_seconds = 0.0
        self._candidate_seconds += frame.duration_seconds
        self._silence_seconds = 0.0

        if self._candidate_seconds < self._min_speech_seconds:
            return False
        if self._candidate_seconds - self._max_candidate_seconds > 1e-9:
            self._block_until_silence()
            return False
        if self._verification_attempts:
            if self._candidate_seconds < self._next_verification_seconds:
                return False
        elif self._candidate_seconds < self._initial_verification_seconds:
            return False
        if self._verification_attempts >= self._max_verification_attempts:
            self._block_until_silence()
            return False

        try:
            result = self._verifier.verify(self._verification_window())
        except (OSError, RuntimeError, TypeError, ValueError, VoiceDependencyUnavailable) as exc:
            self._fail_closed("verifier_unavailable", exc)
            return False
        self.last_verification = result
        self.last_failure_category = result.failure_category
        self._verification_attempts += 1
        self._next_verification_seconds = self._candidate_seconds + self._retry_interval_seconds
        if result.accepted:
            self._clear_candidate()
            return True
        if self._candidate_seconds >= self._max_candidate_seconds:
            self._block_until_silence()
        return False

    def reset(self) -> None:
        """Clear all candidate state and bounded audio immediately."""

        self._clear_candidate()
        self._vad_frames.clear()
        self._stream_seconds = 0.0
        self.last_verification = None
        self.last_failure_category = None

    def _verification_window(self) -> tuple[AudioFrame, ...]:
        return tuple(self._frames)

    def _block_until_silence(self) -> None:
        self._frames.clear()
        self._candidate_active = False
        self._blocked_until_silence = True

    def _clear_candidate(self) -> None:
        self._frames.clear()
        self._candidate_seconds = 0.0
        self._silence_seconds = 0.0
        self._candidate_active = False
        self._blocked_until_silence = False
        self._verification_attempts = 0
        self._next_verification_seconds = 0.0

    def _fail_closed(self, category: str, _error: BaseException) -> None:
        self._available = False
        self.last_failure_category = category
        self._clear_candidate()
        self._vad_frames.clear()

    @staticmethod
    def _trim(frames: deque[AudioFrame], maximum_bytes: int) -> None:
        total = sum(len(item.pcm_s16le) for item in frames)
        while frames and total > maximum_bytes:
            total -= len(frames.popleft().pcm_s16le)


__all__ = [
    "DEFAULT_INITIAL_VERIFICATION_SECONDS",
    "DEFAULT_MAX_CANDIDATE_SECONDS",
    "DEFAULT_MAX_VERIFICATION_ATTEMPTS",
    "DEFAULT_MIN_SPEECH_SECONDS",
    "DEFAULT_RETRY_INTERVAL_SECONDS",
    "DEFAULT_SPEECH_END_SILENCE_SECONDS",
    "DEFAULT_VAD_WINDOW_SECONDS",
    "SAMPLE_RATE_HZ",
    "SpeechGatedHeyJarvisDetector",
]
