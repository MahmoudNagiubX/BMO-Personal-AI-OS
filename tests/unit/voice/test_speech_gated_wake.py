from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.speech_gated_wake import SpeechGatedHeyJarvisDetector
from personal_ai_os.voice.wake_cascade import WakeVerification, normalize_wake_text


def _frame(value: int = 1) -> AudioFrame:
    return AudioFrame(bytes((value, 0)) * 1280)


class _Vad:
    def __init__(self, speech: bool | Sequence[bool] = True) -> None:
        self.speech = speech
        self.calls = 0

    def contains_speech(self, _frames: Sequence[AudioFrame]) -> bool:
        self.calls += 1
        if isinstance(self.speech, bool):
            return self.speech
        index = min(self.calls - 1, len(self.speech) - 1)
        return self.speech[index]


class _Verifier:
    def __init__(self, accepted: bool = True, *, failure: str | None = None) -> None:
        self.accepted = accepted
        self.failure = failure
        self.calls = 0
        self.frame_counts: list[int] = []

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification:
        self.calls += 1
        self.frame_counts.append(len(frames))
        return WakeVerification(
            accepted=self.accepted,
            normalized_word_count=2 if self.accepted else 1,
            wake_token_at_start=self.accepted,
            latency_ms=2.5,
            failure_category=self.failure if not self.accepted else None,
        )


def _detector(vad: _Vad, verifier: _Verifier, **kwargs: object) -> SpeechGatedHeyJarvisDetector:
    return SpeechGatedHeyJarvisDetector(
        vad=vad,
        verifier=verifier,
        initial_verification_seconds=0.32,
        min_speech_seconds=0.32,
        retry_interval_seconds=0.16,
        **kwargs,
    )


def test_speech_starts_a_bounded_candidate_and_then_verifies() -> None:
    vad = _Vad()
    verifier = _Verifier()
    detector = _detector(vad, verifier)

    assert all(detector.detected(_frame()) is False for _ in range(3))
    assert detector.candidate_active is True
    assert detector.detected(_frame()) is True
    assert verifier.calls == 1
    assert verifier.frame_counts == [4]


def test_no_speech_never_invokes_whisper() -> None:
    verifier = _Verifier()
    detector = _detector(_Vad(False), verifier)

    assert all(detector.detected(_frame()) is False for _ in range(20))
    assert verifier.calls == 0
    assert detector.verifier_invocations == 0


def test_rejected_speech_is_retried_only_within_the_bound() -> None:
    verifier = _Verifier(False, failure="wrong_first_token")
    detector = _detector(_Vad(), verifier, max_verification_attempts=2)

    assert all(detector.detected(_frame()) is False for _ in range(20))
    assert verifier.calls == 2
    assert detector.last_failure_category == "wrong_first_token"


def test_silence_resets_a_candidate_and_allows_a_new_one() -> None:
    vad = _Vad((True, True, True, True, False, False, False, False, True, True, True, True))
    verifier = _Verifier()
    detector = _detector(vad, verifier, speech_end_silence_seconds=0.16)

    assert detector.detected(_frame()) is False
    assert detector.detected(_frame()) is False
    assert detector.detected(_frame()) is False
    assert detector.detected(_frame()) is True
    for _ in range(4):
        detector.detected(_frame(2))
    assert detector.candidate_active is False
    assert detector.detected(_frame(3)) is False
    assert detector.detected(_frame(3)) is False
    assert detector.detected(_frame(3)) is False
    assert detector.detected(_frame(3)) is True
    assert verifier.calls == 2


def test_max_candidate_bound_blocks_retries_until_silence() -> None:
    verifier = _Verifier(False, failure="no_transcript")
    detector = _detector(
        _Vad(),
        verifier,
        max_candidate_seconds=0.48,
        vad_window_seconds=0.32,
        max_verification_attempts=4,
    )

    for _ in range(20):
        detector.detected(_frame())
    assert verifier.calls == 2
    assert detector.detected(_frame()) is False


@pytest.mark.parametrize(
    "failure,accepted",
    [(None, True), ("phonetic_near_match", False), ("wrong_first_token", False)],
)
def test_exact_prefix_decision_is_owned_by_the_existing_verifier(
    failure: str | None, accepted: bool
) -> None:
    verifier = _Verifier(accepted, failure=failure)
    detector = _detector(_Vad(), verifier)

    assert all(detector.detected(_frame()) is False for _ in range(3))
    assert detector.detected(_frame()) is accepted


def test_verifier_exception_fails_closed_without_raw_audio_leakage() -> None:
    class BrokenVerifier:
        def verify(self, _frames: Sequence[AudioFrame]) -> WakeVerification:
            raise RuntimeError("wake model unavailable")

    detector = _detector(_Vad(), BrokenVerifier())  # type: ignore[arg-type]

    assert all(detector.detected(_frame()) is False for _ in range(4))
    assert detector.available is False
    assert detector.last_failure_category == "verifier_unavailable"
    assert detector.buffered_bytes == 0


def test_reset_clears_bounded_candidate_state() -> None:
    detector = _detector(_Vad(), _Verifier())
    detector.detected(_frame())
    assert detector.buffered_bytes > 0

    detector.reset()

    assert detector.buffered_bytes == 0
    assert detector.candidate_active is False
    assert detector.verifier_invocations == 0
    assert detector.last_verification is None


def test_detector_has_no_audio_file_persistence_api() -> None:
    source = Path(__file__).resolve().parents[3] / "src/personal_ai_os/voice/speech_gated_wake.py"
    text = source.read_text(encoding="utf-8")
    assert "write_bytes" not in text
    assert "write_text" not in text
    assert "open(" not in text


def test_wake_normalizer_is_reused_for_exact_phrase_contract() -> None:
    assert normalize_wake_text("Hey, Jarvis open VS Code")[:2] == ("hey", "jarvis")
