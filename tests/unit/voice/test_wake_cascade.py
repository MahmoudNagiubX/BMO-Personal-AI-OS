from __future__ import annotations

from collections.abc import Sequence

import pytest

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.wake_cascade import (
    WakeCascadeDetector,
    WakeVerification,
    WhisperWakePhraseVerifier,
    normalize_wake_text,
    starts_with_exact_wake_word,
)


def _frame() -> AudioFrame:
    return AudioFrame(b"\x01\x00" * 320)


class _Recognizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0
        self.frame_counts: list[int] = []

    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        self.calls += 1
        self.frame_counts.append(len(frames))
        return self.text


class _Candidate:
    available = True

    def __init__(self, detected: bool = True) -> None:
        self.detected_value = detected
        self.calls = 0
        self.resets = 0

    def detected(self, _frame: AudioFrame) -> bool:
        self.calls += 1
        return self.detected_value

    def reset(self) -> None:
        self.resets += 1


def test_wake_prefix_accepts_command_following_exact_token() -> None:
    assert normalize_wake_text(" Jarvis, open VS Code! ") == ("jarvis", "open", "vs", "code")
    assert starts_with_exact_wake_word("Jarvis open VS Code") is True
    assert starts_with_exact_wake_word("Hey Jarvis") is False
    assert starts_with_exact_wake_word("Jervis open VS Code") is False


def test_whisper_verifier_returns_sanitized_result_without_transcript() -> None:
    recognizer = _Recognizer("Jarvis check the project")
    result = WhisperWakePhraseVerifier(recognizer).verify((_frame(),))
    assert result.accepted is True
    assert result.wake_token_at_start is True
    assert result.normalized_word_count == 4
    assert result.latency_ms >= 0
    assert not hasattr(result, "transcript")


def test_whisper_verifier_rejects_near_word_and_trailing_wake() -> None:
    assert (
        WhisperWakePhraseVerifier(_Recognizer("Jervis check the project"))
        .verify((_frame(),))
        .failure_category
        == "phonetic_near_match"
    )
    assert (
        WhisperWakePhraseVerifier(_Recognizer("please say Jarvis")).verify((_frame(),)).accepted
        is False
    )


def test_cascade_verifies_only_candidate_speech_and_resets_after_decision() -> None:
    candidate = _Candidate()
    recognizer = _Recognizer("Jarvis open VS Code")
    gate_calls = 0

    def speech_gate(_frame: AudioFrame) -> bool:
        nonlocal gate_calls
        gate_calls += 1
        return True

    detector = WakeCascadeDetector(
        candidate=candidate,
        verifier=WhisperWakePhraseVerifier(recognizer),
        speech_gate=speech_gate,
    )
    assert detector.available is True
    results = [detector.detected(_frame()) for _ in range(16)]
    assert results[-1] is True
    assert candidate.calls == 16
    assert candidate.resets == 1
    assert recognizer.calls == 1
    assert gate_calls == 16
    assert recognizer.frame_counts == [16]
    assert detector.last_verification is not None


def test_cascade_does_not_invoke_candidate_or_verifier_for_non_speech() -> None:
    candidate = _Candidate()
    recognizer = _Recognizer("Jarvis")
    detector = WakeCascadeDetector(
        candidate=candidate,
        verifier=WhisperWakePhraseVerifier(recognizer),
        speech_gate=lambda _frame: False,
    )
    assert detector.detected(_frame()) is False
    assert candidate.calls == 0
    assert recognizer.calls == 0
    assert detector.last_verification is None


def test_cascade_rejects_two_speech_gate_strategies() -> None:
    with pytest.raises(ValueError, match="either"):
        WakeCascadeDetector(
            candidate=_Candidate(),
            verifier=WhisperWakePhraseVerifier(_Recognizer("Jarvis")),
            vad=object(),  # type: ignore[arg-type]
            speech_gate=lambda _frame: True,
        )


def test_cascade_exposes_rejected_verifier_result() -> None:
    detector = WakeCascadeDetector(
        candidate=_Candidate(),
        verifier=WhisperWakePhraseVerifier(_Recognizer("Jervis")),
    )
    assert all(detector.detected(_frame()) is False for _ in range(16))
    assert detector.last_verification == WakeVerification(
        accepted=False,
        normalized_word_count=1,
        wake_token_at_start=False,
        latency_ms=detector.last_verification.latency_ms if detector.last_verification else -1,
        failure_category="phonetic_near_match",
    )


def test_cascade_does_not_verify_the_first_tiny_streaming_frame() -> None:
    candidate = _Candidate()
    recognizer = _Recognizer("Jarvis")
    detector = WakeCascadeDetector(
        candidate=candidate,
        verifier=WhisperWakePhraseVerifier(recognizer),
        speech_gate=lambda _frame: True,
    )

    for _ in range(15):
        assert detector.detected(_frame()) is False
    assert recognizer.calls == 0
    assert detector.detected(_frame()) is True
    assert recognizer.calls == 1
    assert recognizer.frame_counts[0] == 16


def test_cascade_retries_at_a_bounded_cadence_and_caps_attempts() -> None:
    candidate = _Candidate()
    recognizer = _Recognizer("Jervis")
    detector = WakeCascadeDetector(
        candidate=candidate,
        verifier=WhisperWakePhraseVerifier(recognizer),
        speech_gate=lambda _frame: True,
        min_speech_seconds=0.08,
        verification_retry_interval_seconds=0.16,
        max_verification_attempts=2,
    )

    # Each frame is 20 ms. The first attempt is allowed at 80 ms, the second
    # at 240 ms, and no third call may escape the retry budget.
    results = [detector.detected(_frame()) for _ in range(20)]
    assert all(result is False for result in results)
    assert recognizer.calls == 2
    assert recognizer.frame_counts == [4, 13]


def test_cascade_passes_a_rolling_window_to_the_vad() -> None:
    class _Vad:
        def __init__(self) -> None:
            self.window_sizes: list[int] = []

        def contains_speech(self, frames: Sequence[AudioFrame]) -> bool:
            self.window_sizes.append(len(frames))
            return True

    vad = _Vad()
    detector = WakeCascadeDetector(
        candidate=_Candidate(),
        verifier=WhisperWakePhraseVerifier(_Recognizer("Jarvis")),
        vad=vad,
    )

    detector.detected(_frame())
    detector.detected(_frame())
    assert vad.window_sizes == [1, 2]
