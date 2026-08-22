from __future__ import annotations

import copy

import pytest

from scripts.phase_10.validate_wake_model_manifest import validate_manifest


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "phase-10-jarvis-wake-model/v1",
        "model_name": "jarvis-openwakeword-synthetic-v0.1",
        "target_phrase": "Jarvis",
        "engine": "openwakeword==0.6.0 ONNX shared feature extractor",
        "training": {"user_recordings": False, "raw_audio_retained": False},
        "artifact": {
            "path": "BMO/VoiceModels/jarvis.onnx",
            "sha256": "a" * 64,
            "format": "ONNX",
        },
        "license": {"derived_model": "local"},
    }


def test_wake_manifest_is_strict_and_sanitized() -> None:
    validate_manifest(_manifest())


@pytest.mark.parametrize(
    ("field", "value"),
    [("target_phrase", "Hey Jarvis"), ("artifact", {"path": "C:/secret.onnx"})],
)
def test_wake_manifest_rejects_wrong_phrase_or_path(field: str, value: object) -> None:
    payload = _manifest()
    payload[field] = value
    with pytest.raises(ValueError):
        validate_manifest(payload)


def test_wake_manifest_rejects_audio_retention() -> None:
    payload = copy.deepcopy(_manifest())
    payload["training"]["raw_audio_retained"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="retention"):
        validate_manifest(payload)
