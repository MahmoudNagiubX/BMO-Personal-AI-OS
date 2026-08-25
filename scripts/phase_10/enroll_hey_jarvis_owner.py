"""Create the owner-local openWakeWord Hey Jarvis custom verifier.

This is the only enrollment path.  Audio exists only in memory and in a
temporary private WAV directory required by the upstream training API; that
directory is removed and verified empty before the command exits.
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from personal_ai_os.voice.owner_verifier import (
    OWNER_VERIFIER_ARTIFACT,
    default_owner_verifier_dir,
    load_owner_verifier_profile,
    sha256_file,
)
from personal_ai_os.voice.wake_phrase import OPENWAKEWORD_MODEL_SHA256

SAMPLE_RATE_HZ = 16_000


def _write_manifest(
    profile_dir: Path,
    *,
    base_model_path: Path,
    base_model_sha256: str,
    artifact_sha256: str,
    validation: dict[str, Any],
) -> Path:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "phase-10-hey-jarvis-owner-verifier/v1",
        "wake_phrase": "Hey Jarvis",
        "base_model_name": base_model_path.stem,
        "base_model_filename": base_model_path.name,
        "base_model_sha256": base_model_sha256,
        "artifact": {"filename": OWNER_VERIFIER_ARTIFACT, "sha256": artifact_sha256},
        "runtime": "openwakeword==0.6.0; custom_verifier_model",
        "created_at_utc": timestamp,
        "owner_local_only": True,
        "raw_audio_retained": False,
        "validation": validation,
    }
    manifest_path = profile_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _countdown(label: str) -> None:
    print(f"\n{label}", flush=True)
    for value in (3, 2, 1):
        print(f"  {value}...", flush=True)
        time.sleep(1.0)


def _capture(sounddevice: Any, *, seconds: float, device: str | None) -> np.ndarray:
    frames = round(seconds * SAMPLE_RATE_HZ)
    recording = sounddevice.rec(
        frames,
        samplerate=SAMPLE_RATE_HZ,
        channels=1,
        dtype="int16",
        device=device,
    )
    sounddevice.wait()
    result = np.asarray(recording, dtype=np.int16).reshape(-1)
    if len(result) != frames:
        raise RuntimeError("microphone capture returned an unexpected bounded frame count")
    return result


def _write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE_HZ)
        handle.writeframes(samples.tobytes())


def _audio_level(samples: np.ndarray) -> dict[str, float]:
    normalized = samples.astype(np.float32) / 32768.0
    return {
        "rms": round(float(np.sqrt(np.mean(normalized * normalized))), 6),
        "peak": round(float(np.max(np.abs(normalized))), 6),
    }


def _score_clip(model: Any, path: Path, model_name: str) -> float:
    model.reset()
    values: list[float] = []
    with wave.open(str(path), "rb") as handle:
        if (
            handle.getframerate() != SAMPLE_RATE_HZ
            or handle.getnchannels() != 1
            or handle.getsampwidth() != 2
        ):
            raise RuntimeError("enrollment WAV format is invalid")
        while chunk := handle.readframes(1280):
            samples = np.frombuffer(chunk, dtype=np.int16)
            if len(samples) < 1280:
                samples = np.pad(samples, (0, 1280 - len(samples)))
            values.append(float(model.predict(samples).get(model_name, 0.0)))
    return max(values, default=0.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path, default=None)
    parser.add_argument("--input-device")
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    model_path = args.model
    profile_dir = args.profile_dir or default_owner_verifier_dir()
    if not model_path.is_file():
        raise SystemExit("OWNER_ENROLLMENT_BLOCKED: official Hey Jarvis model is missing")
    if sha256_file(model_path).casefold() != OPENWAKEWORD_MODEL_SHA256.casefold():
        raise SystemExit("OWNER_ENROLLMENT_BLOCKED: official Hey Jarvis model checksum mismatch")
    if profile_dir.is_symlink():
        raise SystemExit("OWNER_ENROLLMENT_BLOCKED: owner verifier profile must not be a symlink")
    if profile_dir.exists() and not args.reset:
        raise SystemExit(
            "OWNER_ENROLLMENT_BLOCKED: an owner verifier profile already exists; "
            "use the explicit reset option to reenroll"
        )
    if args.reset and profile_dir.exists():
        shutil.rmtree(profile_dir)

    try:
        sounddevice: Any = importlib.import_module("sounddevice")
    except ImportError as exc:
        raise SystemExit("OWNER_ENROLLMENT_BLOCKED: sounddevice is unavailable") from exc

    try:
        device_info = sounddevice.query_devices(args.input_device, "input")
        device_name = str(device_info.get("name", "unknown microphone"))
        print(f"OWNER ENROLLMENT READY\nMicrophone: {device_name}", flush=True)
        print("Raw audio is temporary and will be deleted before completion.", flush=True)
        parent = profile_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bmo-owner-wake-", dir=str(parent)) as temp_name:
            temp_root = Path(temp_name)
            positives = temp_root / "positive"
            negatives = temp_root / "negative"
            positives.mkdir()
            negatives.mkdir()
            positive_paths: list[Path] = []
            for index, condition in enumerate(
                (
                    "natural Hey Jarvis",
                    "Egyptian-accented Hey Jarvis",
                    "moderate-distance Hey Jarvis",
                    "slightly quieter Hey Jarvis (reserved validation)",
                    "faster Hey Jarvis (reserved validation)",
                ),
                start=1,
            ):
                _countdown(f"Speak {condition} once")
                samples = _capture(sounddevice, seconds=1.6, device=args.input_device)
                path = positives / f"positive_{index}.wav"
                _write_wav(path, samples)
                positive_paths.append(path)
                print(f"  captured scalar level rms/peak={_audio_level(samples)}", flush=True)

            _countdown("Speak normal non-wake speech for about 15 seconds")
            normal = _capture(sounddevice, seconds=15.0, device=args.input_device)
            normal_path = negatives / "normal_speech.wav"
            _write_wav(normal_path, normal)
            _countdown("Remain quiet while room/background sound is sampled")
            ambient = _capture(sounddevice, seconds=7.0, device=args.input_device)
            ambient_path = negatives / "ambient.wav"
            _write_wav(ambient_path, ambient)

            training_positive = positive_paths[:3]
            validation_positive = positive_paths[3:]
            training_negative = [normal_path, ambient_path]
            staging = Path(tempfile.mkdtemp(prefix=".owner-verifier-", dir=str(parent)))
            try:
                artifact = staging / OWNER_VERIFIER_ARTIFACT
                openwakeword: Any = importlib.import_module("openwakeword")

                print("OWNER ENROLLMENT TRAINING", flush=True)
                openwakeword.train_custom_verifier(
                    [str(path) for path in training_positive],
                    [str(path) for path in training_negative],
                    str(artifact),
                    str(model_path),
                    inference_framework="onnx",
                )
                if not artifact.is_file():
                    raise RuntimeError("owner verifier training produced no artifact")
                artifact_sha = sha256_file(artifact)
                manifest_path = _write_manifest(
                    staging,
                    base_model_path=model_path,
                    base_model_sha256=OPENWAKEWORD_MODEL_SHA256,
                    artifact_sha256=artifact_sha,
                    validation={
                        "positive_train_attempts": len(training_positive),
                        "positive_reserved_validation_attempts": len(validation_positive),
                        "negative_train_attempts": len(training_negative),
                        "validation_threshold": 0.5,
                        "raw_audio_retained": False,
                    },
                )
                profile = load_owner_verifier_profile(
                    staging,
                    base_model_path=model_path,
                    expected_base_sha256=OPENWAKEWORD_MODEL_SHA256,
                )
                model = openwakeword.Model(
                    wakeword_models=[str(model_path)],
                    custom_verifier_models=profile.custom_verifier_models,
                    custom_verifier_threshold=0.1,
                    inference_framework="onnx",
                )
                positive_scores = [
                    _score_clip(model, path, model_path.stem) for path in validation_positive
                ]
                negative_scores = [
                    _score_clip(model, path, model_path.stem) for path in training_negative
                ]
                positive_pass = sum(score >= 0.5 for score in positive_scores)
                false_accepts = sum(score >= 0.5 for score in negative_scores)
                validation = {
                    **profile.validation,
                    "positive_validation_detections": positive_pass,
                    "positive_validation_scores": [round(score, 6) for score in positive_scores],
                    "negative_validation_false_accepts": false_accepts,
                    "negative_validation_scores": [round(score, 6) for score in negative_scores],
                    "passed": positive_pass == len(validation_positive) and false_accepts == 0,
                }
                manifest_path.unlink()
                _write_manifest(
                    staging,
                    base_model_path=model_path,
                    base_model_sha256=OPENWAKEWORD_MODEL_SHA256,
                    artifact_sha256=artifact_sha,
                    validation=validation,
                )
                if validation["passed"] is not True:
                    raise RuntimeError(
                        "owner verifier reserved validation did not pass "
                        f"positive={positive_pass}/{len(validation_positive)} "
                        f"negative_false_accepts={false_accepts}"
                    )
                profile_dir.mkdir(parents=True, exist_ok=False)
                shutil.copy2(
                    staging / OWNER_VERIFIER_ARTIFACT,
                    profile_dir / OWNER_VERIFIER_ARTIFACT,
                )
                shutil.copy2(staging / "manifest.json", profile_dir / "manifest.json")
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        if any(profile_dir.rglob("*.wav")):
            raise RuntimeError("owner enrollment temporary audio cleanup failed")
        print(
            "OWNER_ENROLLMENT_PASS "
            f"profile={profile_dir} positive_validation={positive_pass}/"
            f"{len(validation_positive)} negative_false_accepts={false_accepts} "
            "raw_audio_retained=false",
            flush=True,
        )
        return 0
    except KeyboardInterrupt:
        raise SystemExit("OWNER_ENROLLMENT_ABORTED: temporary audio was discarded") from None
    except Exception as exc:
        sanitized = " ".join(str(exc).split())[:220]
        raise SystemExit(f"OWNER_ENROLLMENT_BLOCKED: {type(exc).__name__}: {sanitized}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
