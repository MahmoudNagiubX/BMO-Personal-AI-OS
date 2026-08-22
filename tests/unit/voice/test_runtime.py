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


def test_production_runtime_requires_explicit_custom_wake_model(tmp_path: Path) -> None:
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
    with pytest.raises(ValueError, match="explicit local Jarvis wake-word model"):
        from personal_ai_os.voice.runtime import build_local_runtime

        build_local_runtime(config, core=object())
