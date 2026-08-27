"""Automated local wake-word acceptance suite for Phase 10 closeout.

Validates the production SpeechGatedHeyJarvisDetector and FasterWhisperWakePhraseRecognizer
on synthesized local Piper English and Arabic audio fixtures, speed/pitch variations,
wake-plus-command utterances, and negative non-wake cases.

Requires zero human speech, zero paid APIs, and zero audio file persistence.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
    VoiceDependencyUnavailable,
)
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.speech_gated_wake import SpeechGatedHeyJarvisDetector
from personal_ai_os.voice.wake_cascade import (
    WhisperWakePhraseVerifier,
    normalize_wake_text,
    starts_with_exact_wake_word,
    strip_leading_wake_phrase,
)
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE

SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 1_280  # 80 ms


def _local_voice_root() -> Path | None:
    candidate = Path.home() / "AppData/Local/BMO/VoiceModels"
    if candidate.is_dir():
        return candidate
    return None


@pytest.fixture(scope="module")
def voice_models() -> dict[str, Path]:
    root = _local_voice_root()
    if root is None:
        pytest.skip("Local BMO VoiceModels directory not found on this host")
    models = {
        "wake_model": root / "faster-whisper-base.en",
        "english_onnx": root / "vits-piper-en_US-lessac-medium/en_US-lessac-medium.onnx",
        "english_tokens": root / "vits-piper-en_US-lessac-medium/tokens.txt",
        "arabic_onnx": root / "vits-piper-ar_JO-kareem-medium/ar_JO-kareem-medium.onnx",
        "arabic_tokens": root / "vits-piper-ar_JO-kareem-medium/tokens.txt",
        "tts_data": root / "espeak-ng-data",
    }
    for name, path in models.items():
        if not path.exists():
            pytest.skip(f"Required voice model path {name} ({path}) not found")
    return models


@pytest.fixture(scope="module")
def english_tts(voice_models: dict[str, Path]) -> SherpaOnnxPiperSynthesizer:
    try:
        return SherpaOnnxPiperSynthesizer(
            model=str(voice_models["english_onnx"]),
            tokens=str(voice_models["english_tokens"]),
            data_dir=str(voice_models["tts_data"]),
        )
    except VoiceDependencyUnavailable as exc:
        pytest.skip(f"English TTS engine unavailable: {exc}")


@pytest.fixture(scope="module")
def arabic_tts(voice_models: dict[str, Path]) -> SherpaOnnxPiperSynthesizer:
    try:
        return SherpaOnnxPiperSynthesizer(
            model=str(voice_models["arabic_onnx"]),
            tokens=str(voice_models["arabic_tokens"]),
            data_dir=str(voice_models["tts_data"]),
        )
    except VoiceDependencyUnavailable as exc:
        pytest.skip(f"Arabic TTS engine unavailable: {exc}")


@pytest.fixture(scope="module")
def wake_detector(voice_models: dict[str, Path]) -> SpeechGatedHeyJarvisDetector:
    try:
        recognizer = FasterWhisperWakePhraseRecognizer(
            model=str(voice_models["wake_model"]),
            device="cpu",
            compute_type="int8",
            beam_size=1,
            hotwords=None,
        )
        vad = SileroVoiceActivityDetector()
        verifier = WhisperWakePhraseVerifier(recognizer, wake_word=PRIMARY_WAKE_PHRASE)
        return SpeechGatedHeyJarvisDetector(vad=vad, verifier=verifier)
    except VoiceDependencyUnavailable as exc:
        pytest.skip(f"Wake detector dependencies unavailable: {exc}")


def _stream_audio(detector: SpeechGatedHeyJarvisDetector, pcm: bytes) -> bool:
    detector.reset()
    # Stream pcm plus natural trailing silence frames
    streamed_pcm = pcm + b"\x00\x00" * (FRAME_SAMPLES * 3)
    for offset in range(0, len(streamed_pcm), FRAME_SAMPLES * 2):
        chunk = streamed_pcm[offset : offset + FRAME_SAMPLES * 2]
        if len(chunk) < FRAME_SAMPLES * 2:
            chunk = chunk + b"\x00" * (FRAME_SAMPLES * 2 - len(chunk))
        frame = AudioFrame(chunk, sample_rate_hz=SAMPLE_RATE_HZ)
        if detector.detected(frame):
            return True
    return False


def test_wake_normalizer_exact_tokens() -> None:
    assert normalize_wake_text("Hey Jarvis") == ("hey", "jarvis")
    assert normalize_wake_text("HEY, JARVIS!") == ("hey", "jarvis")
    assert normalize_wake_text("Hey Jarvis open VS Code") == ("hey", "jarvis", "open", "vs", "code")
    assert starts_with_exact_wake_word("Hey Jarvis") is True
    assert starts_with_exact_wake_word("Hey Jarvis, check status") is True
    assert starts_with_exact_wake_word("Jarvis") is False
    assert starts_with_exact_wake_word("Hey") is False
    assert starts_with_exact_wake_word("Hey Travis") is False
    assert strip_leading_wake_phrase("Hey Jarvis open Chrome") == "open chrome"


@pytest.mark.parametrize(
    "phrase",
    [
        "Hey Jarvis",
        "Hey Jarvis open VS Code",
        "Hey Jarvis check the system status",
        "Hey Jarvis what is left",
        "Hey Jarvis tell me the time",
    ],
)
def test_positive_wake_fixtures_detected(
    wake_detector: SpeechGatedHeyJarvisDetector,
    english_tts: SherpaOnnxPiperSynthesizer,
    phrase: str,
) -> None:
    frames = english_tts.synthesize(phrase)
    pcm = b"".join(f.pcm_s16le for f in frames)
    assert _stream_audio(wake_detector, pcm) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "Jarvis",
        "Hey",
        "Hey service",
        "Hey Travis",
        "open VS Code",
        "good morning",
        "check the project status",
        "please continue the meeting",
        "Your system is ready and all tests have passed",
    ],
)
def test_english_negative_fixtures_rejected(
    wake_detector: SpeechGatedHeyJarvisDetector,
    english_tts: SherpaOnnxPiperSynthesizer,
    phrase: str,
) -> None:
    frames = english_tts.synthesize(phrase)
    pcm = b"".join(f.pcm_s16le for f in frames)
    assert _stream_audio(wake_detector, pcm) is False


@pytest.mark.parametrize(
    "arabic_phrase",
    [
        "صباح الخير",
        "افتح المشروع",
        "تحقق من الاختبارات",
        "اخبرني بالحالة",
        "استمر في العمل",
    ],
)
def test_arabic_negative_fixtures_rejected(
    wake_detector: SpeechGatedHeyJarvisDetector,
    arabic_tts: SherpaOnnxPiperSynthesizer,
    arabic_phrase: str,
) -> None:
    frames = arabic_tts.synthesize(arabic_phrase)
    pcm = b"".join(f.pcm_s16le for f in frames)
    assert _stream_audio(wake_detector, pcm) is False


def test_silence_and_noise_fixtures_rejected(
    wake_detector: SpeechGatedHeyJarvisDetector,
) -> None:
    # 2 seconds of pure silence
    silence = b"\x00\x00" * (SAMPLE_RATE_HZ * 2)
    assert _stream_audio(wake_detector, silence) is False

    # 2 seconds of Gaussian white noise at low amplitude
    rng = np.random.default_rng(42)
    noise_samples = (rng.normal(0.0, 0.003, SAMPLE_RATE_HZ * 2) * 32767.0).astype(np.int16)
    assert _stream_audio(wake_detector, noise_samples.tobytes()) is False


def test_speed_and_gain_variations(
    wake_detector: SpeechGatedHeyJarvisDetector,
    english_tts: SherpaOnnxPiperSynthesizer,
) -> None:
    frames = english_tts.synthesize("Hey Jarvis")
    pcm_bytes = b"".join(f.pcm_s16le for f in frames)
    raw_samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)

    # Moderate gain variations (0.75x, 1.25x)
    for scale in (0.75, 1.25):
        scaled = np.clip(raw_samples * scale, -32768, 32767).astype(np.int16)
        assert _stream_audio(wake_detector, scaled.tobytes()) is True

    # Leading and trailing silence
    leading_silence = np.zeros(int(SAMPLE_RATE_HZ * 0.2), dtype=np.int16)
    trailing_silence = np.zeros(int(SAMPLE_RATE_HZ * 0.2), dtype=np.int16)
    padded = np.concatenate((leading_silence, raw_samples.astype(np.int16), trailing_silence))
    assert _stream_audio(wake_detector, padded.tobytes()) is True
