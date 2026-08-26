from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.phase_10.validate_wake_model_manifest import validate_manifest


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "phase-10-hey-jarvis-wake-model/v1",
        "model_name": "hey_jarvis_v0.1",
        "target_phrase": "Hey Jarvis",
        "engine": "openwakeword==0.6.0; onnxruntime",
        "repository": "https://github.com/dscripka/openWakeWord",
        "revision": "v0.5.1",
        "commit": "1eec2158c5c54150ac5f4c15065adacb1003b1e7",
        "training": {"user_recordings": False, "raw_audio_retained": False},
        "artifact": {
            "path": "models/hey_jarvis_v0.1.onnx",
            "sha256": "a" * 64,
            "format": "ONNX",
        },
        "license": {"engine": "Apache-2.0", "pretrained_model": "CC-BY-NC-SA-4.0"},
    }


def test_wake_manifest_is_strict_and_sanitized() -> None:
    validate_manifest(_manifest())


@pytest.mark.parametrize(
    ("field", "value"),
    [("target_phrase", "Jarvis"), ("artifact", {"path": "C:/secret.onnx"})],
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


def test_wake_manifest_requires_matching_format() -> None:
    payload = _manifest()
    payload["artifact"] = {
        "path": "models/hey_jarvis_v0.1.tflite",
        "sha256": "b" * 64,
        "format": "TFLite",
    }
    validate_manifest(payload)
    payload["artifact"]["format"] = "ONNX"  # type: ignore[index]
    with pytest.raises(ValueError, match="format"):
        validate_manifest(payload)


def test_wake_manifest_rejects_relative_path_traversal() -> None:
    payload = _manifest()
    payload["artifact"]["path"] = "../outside.onnx"  # type: ignore[index]
    with pytest.raises(ValueError, match="path"):
        validate_manifest(payload)


def test_rhasspy_manifest_is_pinned_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "infrastructure/tuf/rhasspy_wake_model_manifest.json").read_text(encoding="utf-8")
    )
    validate_manifest(payload)


def test_rhasspy_manifest_rejects_model_identity_tampering() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "infrastructure/tuf/rhasspy_wake_model_manifest.json").read_text(encoding="utf-8")
    )
    payload["artifact"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="installed pinned identity"):
        validate_manifest(payload)
