from __future__ import annotations

from pathlib import Path

import pytest

from personal_ai_os.voice.runtime import VoiceRuntimeConfig


def test_runtime_requires_explicit_external_tts_paths() -> None:
    with pytest.raises(ValueError, match="Arabic TTS"):
        VoiceRuntimeConfig().validate()


def test_runtime_paths_are_not_derived_from_home() -> None:
    config = VoiceRuntimeConfig(
        arabic_tts_model=Path("C:/voice/ar/model.onnx"),
        arabic_tts_tokens=Path("C:/voice/ar/tokens.txt"),
        english_tts_model=Path("C:/voice/en/model.onnx"),
        english_tts_tokens=Path("C:/voice/en/tokens.txt"),
    )
    assert config.arabic_tts_model is not None
    assert "home" not in str(config.arabic_tts_model).casefold()


def test_production_runtime_uses_speech_gated_faster_whisper(tmp_path: Path) -> None:
    root = tmp_path / "voice"
    root.mkdir()
    for name in ("ar.onnx", "ar.tokens", "en.onnx", "en.tokens"):
        (root / name).write_bytes(b"placeholder")
    config = VoiceRuntimeConfig(
        arabic_tts_model=root / "ar.onnx",
        arabic_tts_tokens=root / "ar.tokens",
        english_tts_model=root / "en.onnx",
        english_tts_tokens=root / "en.tokens",
        tts_data_dir=root,
    )
    config.validate()
    assert config.wake_word_backend == "speech_gated_faster_whisper"
    assert config.wake_phrase == "Hey Jarvis"
    assert config.wake_word_model == "base.en"
    assert config.wake_word_device == "cpu"
    assert config.wake_word_compute_type == "int8"
    assert config.wake_word_beam_size == 1
    assert config.wake_word_hotwords is None


def test_runtime_rejects_wrong_backend() -> None:
    with pytest.raises(ValueError, match="unsupported wake-word backend"):
        config = VoiceRuntimeConfig(wake_word_backend="legacy")  # type: ignore[arg-type]
        config.validate()
