"""Create a local, provisional owner verifier without retaining raw audio."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import tempfile
import time
import wave
from dataclasses import dataclass
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
from scripts.phase_10.owner_verifier_training import (
    score_base_clip,
    train_calibrated_verifier,
)

SAMPLE_RATE_HZ = 16_000
POSITIVE_CAPTURE_SECONDS = 2.1
NORMAL_SPEECH_SECONDS = 15.0
NORMAL_TRAIN_SECONDS = 10.0
AMBIENT_SECONDS = 7.0
AMBIENT_TRAIN_SECONDS = 4.0
BASE_CANDIDATE_RECALL_TARGET = 0.995
TEMPORAL_POLICY = "moving_max"
TEMPORAL_WINDOW_FRAMES = 3
REQUIRED_HITS_IN_WINDOW = 1
DEACTIVATION_THRESHOLD = 0.05


class AudioQualityError(RuntimeError):
    """Raised when a bounded positive capture cannot be distinguished from ambient."""


@dataclass(frozen=True, slots=True)
class AudioLevels:
    rms: float
    peak: float

    def as_dict(self) -> dict[str, float]:
        return {"rms": round(self.rms, 6), "peak": round(self.peak, 6)}


def _wake_contract(
    final_threshold: float | None,
    *,
    base_threshold: float,
    base_calibration: dict[str, Any],
) -> dict[str, Any]:
    return {
        "base_candidate_invoke_threshold": base_threshold,
        "base_candidate_recall_target": BASE_CANDIDATE_RECALL_TARGET,
        "base_candidate_threshold_status": "calibrated_broad_synthetic",
        "base_candidate_calibration": base_calibration,
        "final_owner_verifier_accept_threshold": final_threshold,
        "temporal_policy": TEMPORAL_POLICY,
        "temporal_window_frames": TEMPORAL_WINDOW_FRAMES,
        "required_hits_in_window": REQUIRED_HITS_IN_WINDOW,
        "deactivation_threshold": DEACTIVATION_THRESHOLD,
        "openwakeword_vad_threshold": None,
    }


def _write_manifest(
    profile_dir: Path,
    *,
    base_model_path: Path,
    artifact_sha256: str,
    validation: dict[str, Any],
    final_threshold: float | None,
    base_threshold: float,
    base_calibration: dict[str, Any],
) -> Path:
    payload = {
        "schema_version": "phase-10-hey-jarvis-owner-verifier/v2",
        "wake_phrase": "Hey Jarvis",
        "base_model_name": base_model_path.stem,
        "base_model_filename": base_model_path.name,
        "base_model_sha256": OPENWAKEWORD_MODEL_SHA256,
        "artifact": {"filename": OWNER_VERIFIER_ARTIFACT, "sha256": artifact_sha256},
        "runtime": "openwakeword==0.6.0; custom_verifier_model",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "owner_local_only": True,
        "raw_audio_retained": False,
        "production_ready": False,
        "wake_contract": _wake_contract(
            final_threshold,
            base_threshold=base_threshold,
            base_calibration=base_calibration,
        ),
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
    print("  GO", flush=True)


def _capture(sounddevice: Any, *, seconds: float, device: str | None) -> np.ndarray:
    frames = round(seconds * SAMPLE_RATE_HZ)
    recording = sounddevice.rec(
        frames, samplerate=SAMPLE_RATE_HZ, channels=1, dtype="int16", device=device
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


def _read_wav_samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (
            SAMPLE_RATE_HZ,
            1,
            2,
        ):
            raise RuntimeError("enrollment WAV format is invalid")
        return np.frombuffer(handle.readframes(10**9), dtype=np.int16).copy()


def _audio_levels(samples: np.ndarray) -> AudioLevels:
    normalized = samples.astype(np.float32) / 32768.0
    return AudioLevels(
        rms=float(np.sqrt(np.mean(normalized * normalized))),
        peak=float(np.max(np.abs(normalized))),
    )


def _positive_audio_is_usable(level: AudioLevels, ambient: AudioLevels) -> bool:
    """Use bounded device-relative SNR-ish gates, not a fixed speech threshold."""

    return level.rms >= max(0.0004, ambient.rms * 2.5) and level.peak >= max(
        0.003, ambient.peak * 1.75
    )


def _capture_positive(
    sounddevice: Any, *, condition: str, device: str | None, ambient: AudioLevels
) -> tuple[np.ndarray, AudioLevels]:
    for attempt in (1, 2):
        _countdown(f"Speak {condition} once (attempt {attempt}/2)")
        samples = _capture(sounddevice, seconds=POSITIVE_CAPTURE_SECONDS, device=device)
        levels = _audio_levels(samples)
        print(f"  captured scalar level rms/peak={levels.as_dict()}", flush=True)
        if _positive_audio_is_usable(levels, ambient):
            return samples, levels
        if attempt == 1:
            print("  audio was too close to ambient; one safe recapture follows", flush=True)
    raise AudioQualityError(
        f"OWNER_ENROLLMENT_BLOCKED_AUDIO_QUALITY condition={condition!r} "
        f"ambient={ambient.as_dict()} captured={levels.as_dict()}"
    )


def _split_samples(samples: np.ndarray, train_seconds: float) -> tuple[np.ndarray, np.ndarray]:
    split = round(train_seconds * SAMPLE_RATE_HZ)
    if not 0 < split < len(samples):
        raise ValueError("negative recording cannot be split into non-overlapping partitions")
    return samples[:split], samples[split:]


def _score_clip(model: Any, path: Path, model_name: str) -> float:
    model.reset()
    values: list[float] = []
    with wave.open(str(path), "rb") as handle:
        if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (
            SAMPLE_RATE_HZ,
            1,
            2,
        ):
            raise RuntimeError("enrollment WAV format is invalid")
        while chunk := handle.readframes(1280):
            samples = np.frombuffer(chunk, dtype=np.int16)
            if len(samples) < 1280:
                samples = np.pad(samples, (0, 1280 - len(samples)))
            values.append(float(model.predict(samples).get(model_name, 0.0)))
    return max(values, default=0.0)


def _summary(scores: list[float]) -> dict[str, float]:
    return {
        "min": round(min(scores), 6),
        "median": round(float(np.median(scores)), 6),
        "max": round(max(scores), 6),
    }


def _select_final_accept_threshold(positive: list[float], negative: list[float]) -> float | None:
    """Select only a separating threshold; never use a fixed verifier threshold."""

    if not positive or not negative or min(positive) <= max(negative):
        return None
    return (min(positive) + max(negative)) / 2.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path, default=None)
    parser.add_argument("--input-device")
    parser.add_argument("--base-calibration", type=Path, required=True)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    model_path: Path = args.model
    profile_dir: Path = args.profile_dir or default_owner_verifier_dir()
    try:
        base_evidence = json.loads(args.base_calibration.read_text(encoding="utf-8"))
        base_calibration = base_evidence["base_candidate_calibration"]
        base_threshold = float(base_calibration["selected_threshold"])
        if (
            float(base_calibration["candidate_recall"]) < BASE_CANDIDATE_RECALL_TARGET
            or base_calibration["streaming_path"] != "JarvisVoicePipeline.on_capture_frame"
            or base_calibration["internal_vad_disabled"] is not True
        ):
            raise ValueError("base candidate calibration does not meet the production gate")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(
            f"OWNER_ENROLLMENT_BLOCKED: invalid base candidate calibration: {exc}"
        ) from exc
    if (
        not model_path.is_file()
        or sha256_file(model_path).casefold() != OPENWAKEWORD_MODEL_SHA256.casefold()
    ):
        raise SystemExit(
            "OWNER_ENROLLMENT_BLOCKED: official Hey Jarvis model is missing or invalid"
        )
    if profile_dir.is_symlink():
        raise SystemExit("OWNER_ENROLLMENT_BLOCKED: owner verifier profile must not be a symlink")
    if profile_dir.exists() and not args.reset:
        raise SystemExit(
            "OWNER_ENROLLMENT_BLOCKED: profile exists; use explicit --reset to reenroll"
        )
    if args.reset and profile_dir.exists():
        shutil.rmtree(profile_dir)
    try:
        sounddevice: Any = importlib.import_module("sounddevice")
        openwakeword: Any = importlib.import_module("openwakeword")
    except ImportError as exc:
        raise SystemExit(
            "OWNER_ENROLLMENT_BLOCKED: local enrollment dependency is unavailable"
        ) from exc

    staging: Path | None = None
    installed = False
    try:
        device_name = str(
            sounddevice.query_devices(args.input_device, "input").get("name", "unknown microphone")
        )
        print(f"OWNER ENROLLMENT READY\nMicrophone: {device_name}", flush=True)
        print("Raw audio is temporary and will be deleted before completion.", flush=True)
        parent = profile_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bmo-owner-wake-", dir=str(parent)) as temporary:
            temp_root = Path(temporary)
            positive_dir = temp_root / "positive"
            negative_dir = temp_root / "negative"
            positive_dir.mkdir()
            negative_dir.mkdir()
            _countdown("Remain quiet for the bounded ambient baseline")
            baseline_samples = _capture(sounddevice, seconds=1.0, device=args.input_device)
            baseline = _audio_levels(baseline_samples)
            print(f"  ambient scalar rms/peak={baseline.as_dict()}", flush=True)
            positive_paths: list[Path] = []
            quality: dict[str, dict[str, float]] = {}
            conditions = (
                "natural Hey Jarvis",
                "Egyptian-accented Hey Jarvis",
                "moderate-distance Hey Jarvis",
                "slightly quieter Hey Jarvis (reserved validation)",
                "faster Hey Jarvis (reserved validation)",
            )
            for index, condition in enumerate(
                conditions,
                1,
            ):
                samples, levels = _capture_positive(
                    sounddevice, condition=condition, device=args.input_device, ambient=baseline
                )
                path = positive_dir / f"positive_{index}.wav"
                context = baseline_samples[-round(0.8 * SAMPLE_RATE_HZ) :]
                _write_wav(path, np.concatenate((context, samples)))
                positive_paths.append(path)
                quality[condition] = levels.as_dict()
            _countdown("Speak normal non-wake speech for about 15 seconds")
            normal_train, normal_hold = _split_samples(
                _capture(sounddevice, seconds=NORMAL_SPEECH_SECONDS, device=args.input_device),
                NORMAL_TRAIN_SECONDS,
            )
            _countdown("Remain quiet while room/background sound is sampled")
            ambient_train, ambient_hold = _split_samples(
                _capture(sounddevice, seconds=AMBIENT_SECONDS, device=args.input_device),
                AMBIENT_TRAIN_SECONDS,
            )
            paths = {
                "normal_train": negative_dir / "normal_train.wav",
                "normal_hold": negative_dir / "normal_holdout.wav",
                "ambient_train": negative_dir / "ambient_train.wav",
                "ambient_hold": negative_dir / "ambient_holdout.wav",
            }
            for name, samples in (
                ("normal_train", normal_train),
                ("normal_hold", normal_hold),
                ("ambient_train", ambient_train),
                ("ambient_hold", ambient_hold),
            ):
                _write_wav(paths[name], samples)
            base_model = openwakeword.Model(
                wakeword_models=[str(model_path)],
                inference_framework="onnx",
                vad_threshold=0.0,
            )
            training_positive_base_scores: list[dict[str, float | int]] = []
            reserved_positive_base_scores: list[dict[str, float | int]] = []
            for index, path in enumerate(positive_paths):
                diagnostics = score_base_clip(
                    base_model,
                    _read_wav_samples(path),
                    model_path.stem,
                    threshold=base_threshold,
                )
                target = (
                    training_positive_base_scores if index < 3 else reserved_positive_base_scores
                )
                target.append(diagnostics.as_dict())
                if diagnostics.candidate_frames == 0:
                    print(
                        (
                            f"base candidate miss for {conditions[index]}; "
                            "one bounded recapture follows"
                        ),
                        flush=True,
                    )
                    samples, levels = _capture_positive(
                        sounddevice,
                        condition=f"{conditions[index]} base-candidate retry",
                        device=args.input_device,
                        ambient=baseline,
                    )
                    context = baseline_samples[-round(0.8 * SAMPLE_RATE_HZ) :]
                    _write_wav(path, np.concatenate((context, samples)))
                    quality[conditions[index]] = levels.as_dict()
                    diagnostics = score_base_clip(
                        base_model,
                        _read_wav_samples(path),
                        model_path.stem,
                        threshold=base_threshold,
                    )
                    target[-1] = diagnostics.as_dict()
                    if diagnostics.candidate_frames == 0:
                        raise RuntimeError(
                            "OWNER_ENROLLMENT_BLOCKED_BASE_CANDIDATE "
                            f"positive_index={index + 1} scalar={diagnostics.as_dict()}"
                        )
            print(f"base_candidate_invoke_threshold={base_threshold}", flush=True)
            print(f"training_positive_base_scores={training_positive_base_scores}", flush=True)
            print(f"reserved_positive_base_scores={reserved_positive_base_scores}", flush=True)
            staging = Path(tempfile.mkdtemp(prefix=".owner-verifier-", dir=str(parent)))
            artifact = staging / OWNER_VERIFIER_ARTIFACT
            print("OWNER ENROLLMENT TRAINING", flush=True)
            training_stats = train_calibrated_verifier(
                [str(path) for path in positive_paths[:3]],
                [paths["normal_train"], paths["ambient_train"]],
                base_model_path=model_path,
                output_path=artifact,
                base_candidate_invoke_threshold=base_threshold,
            )
            if not artifact.is_file():
                raise RuntimeError("owner verifier training produced no artifact")
            artifact_sha = sha256_file(artifact)
            initial = {
                "positive_train_attempts": 3,
                "positive_reserved_validation_attempts": 2,
                "negative_train_duration_seconds": NORMAL_TRAIN_SECONDS + AMBIENT_TRAIN_SECONDS,
                "negative_holdout_duration_seconds": (NORMAL_SPEECH_SECONDS - NORMAL_TRAIN_SECONDS)
                + (AMBIENT_SECONDS - AMBIENT_TRAIN_SECONDS),
                "raw_audio_retained": False,
                "base_candidate_calibration": base_calibration,
                "training_positive_base_scores": training_positive_base_scores,
                "reserved_positive_base_scores": reserved_positive_base_scores,
                "training_stats": training_stats,
            }
            _write_manifest(
                staging,
                base_model_path=model_path,
                artifact_sha256=artifact_sha,
                validation=initial,
                final_threshold=None,
                base_threshold=base_threshold,
                base_calibration=base_calibration,
            )
            profile = load_owner_verifier_profile(
                staging,
                base_model_path=model_path,
                expected_base_sha256=OPENWAKEWORD_MODEL_SHA256,
                require_production_ready=False,
            )
            verifier_model = openwakeword.Model(
                wakeword_models=[str(model_path)],
                custom_verifier_models=profile.custom_verifier_models,
                custom_verifier_threshold=base_threshold,
                inference_framework="onnx",
            )
            reserved = positive_paths[3:]
            base_scores = [float(item["maximum_score"]) for item in reserved_positive_base_scores]
            final_scores = [_score_clip(verifier_model, path, model_path.stem) for path in reserved]
            holdout_paths = [paths["normal_hold"], paths["ambient_hold"]]
            holdout_scores = [
                _score_clip(verifier_model, path, model_path.stem) for path in holdout_paths
            ]
            final_threshold = _select_final_accept_threshold(final_scores, holdout_scores)
            detections = (
                sum(score >= final_threshold for score in final_scores)
                if final_threshold is not None
                else 0
            )
            false_accepts = (
                sum(score >= final_threshold for score in holdout_scores)
                if final_threshold is not None
                else 0
            )
            validation = {
                **initial,
                "ambient_baseline": baseline.as_dict(),
                "positive_capture_levels": quality,
                "reserved_base_candidate_scores": [round(score, 6) for score in base_scores],
                "reserved_final_verifier_scores": [round(score, 6) for score in final_scores],
                "negative_holdout_final_verifier_scores": [
                    round(score, 6) for score in holdout_scores
                ],
                "reserved_base_candidate_summary": _summary(base_scores),
                "reserved_final_verifier_summary": _summary(final_scores),
                "negative_holdout_summary": _summary(holdout_scores),
                "lowest_positive_minus_highest_negative": round(
                    min(final_scores) - max(holdout_scores), 6
                ),
                "final_threshold_selected": None
                if final_threshold is None
                else round(final_threshold, 6),
                "positive_validation_detections": detections,
                "negative_validation_false_accepts": false_accepts,
                "passed": final_threshold is not None
                and detections == len(final_scores)
                and false_accepts == 0,
                "raw_audio_retained": False,
            }
            (staging / "manifest.json").unlink()
            _write_manifest(
                staging,
                base_model_path=model_path,
                artifact_sha256=artifact_sha,
                validation=validation,
                final_threshold=final_threshold,
                base_threshold=base_threshold,
                base_calibration=base_calibration,
            )
        if any(staging.rglob("*.wav")):
            raise RuntimeError("owner enrollment profile contains raw audio")
        os.replace(staging, profile_dir)
        installed = True
        state = (
            "OWNER_ENROLLMENT_PROVISIONAL_READY"
            if final_threshold is not None
            else "OWNER_ENROLLMENT_PROVISIONAL_CALIBRATION_BLOCKED"
        )
        print(state, flush=True)
        positive_output = validation["reserved_final_verifier_scores"]
        negative_output = validation["negative_holdout_final_verifier_scores"]
        print(
            f"final_threshold={None if final_threshold is None else round(final_threshold, 6)} "
            f"positive={positive_output} negative={negative_output} raw_audio_retained=false",
            flush=True,
        )
        return 0 if final_threshold is not None else 2
    except KeyboardInterrupt:
        raise SystemExit("OWNER_ENROLLMENT_ABORTED: temporary audio was discarded") from None
    except Exception as exc:
        raise SystemExit(
            f"OWNER_ENROLLMENT_BLOCKED: {type(exc).__name__}: {' '.join(str(exc).split())[:220]}"
        ) from exc
    finally:
        if staging is not None and staging.exists() and not installed:
            shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
