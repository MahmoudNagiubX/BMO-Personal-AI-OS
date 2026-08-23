"""Validate the sanitized provenance manifest for the local Jarvis artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_manifest(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "phase-10-jarvis-wake-model/v1":
        raise ValueError("unsupported wake-model manifest schema")
    if payload.get("target_phrase") != "Jarvis":
        raise ValueError("wake-model target phrase must be exactly Jarvis")
    training = payload.get("training")
    artifact = payload.get("artifact")
    license_data = payload.get("license")
    engine = payload.get("engine")
    if not isinstance(engine, str) or not engine.strip():
        raise ValueError("wake-model engine is required")
    if not isinstance(training, dict) or not isinstance(artifact, dict):
        raise ValueError("training and artifact objects are required")
    if not isinstance(license_data, dict):
        raise ValueError("license object is required")
    if training.get("user_recordings") is not False:
        raise ValueError("user recordings must be false")
    if training.get("raw_audio_retained") is not False:
        raise ValueError("raw audio retention must be false")
    digest = artifact.get("sha256")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise ValueError("artifact sha256 must be a full lowercase digest")
    path = artifact.get("path")
    path_object = Path(path) if isinstance(path, str) else Path()
    if (
        not isinstance(path, str)
        or path_object.is_absolute()
        or ".." in path_object.parts
        or path_object.suffix.casefold() not in {".onnx", ".tflite"}
    ):
        raise ValueError("artifact path must be a sanitized relative ONNX or TFLite path")
    artifact_format = artifact.get("format")
    expected_format = "TFLite" if Path(path).suffix.casefold() == ".tflite" else "ONNX"
    if artifact_format != expected_format:
        raise ValueError("artifact format does not match the artifact path")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("manifest root must be an object")
        validate_manifest(payload)
        if args.artifact is not None:
            actual = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
            if actual != payload["artifact"]["sha256"]:
                raise ValueError("artifact sha256 mismatch")
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"PHASE_10_WAKE_MANIFEST_INVALID: {exc}", file=sys.stderr)
        return 1
    print("PHASE_10_WAKE_MANIFEST_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
