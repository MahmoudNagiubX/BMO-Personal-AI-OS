"""Benchmark English-specific Whisper wake verification without retaining audio.

The corpus and all candidate windows are temporary. Output contains only model
identity, decode configuration, scalar timings, and aggregate error categories.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    PersonalizedMfccDtwWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
)
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import serialize_mfcc_profile
from personal_ai_os.voice.wake_cascade import WhisperWakePhraseVerifier

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RATE_HZ = 16_000
MODEL_METADATA: dict[str, dict[str, str]] = {
    "tiny.en": {
        "repository": "Systran/faster-whisper-tiny.en",
        "revision": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
        "license": "MIT",
    },
    "base.en": {
        "repository": "Systran/faster-whisper-base.en",
        "revision": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
        "license": "MIT",
    },
    "small.en": {
        "repository": "Systran/faster-whisper-small.en",
        "revision": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
        "license": "MIT",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(path: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    total = 0
    for item in sorted(file for file in path.rglob("*") if file.is_file()):
        relative = item.relative_to(path).as_posix()
        size = item.stat().st_size
        files[relative] = {"bytes": size, "sha256": _sha256(item)}
        total += size
    return {"basename": path.name, "bytes": total, "files": files}


def _audio_frame(audio: np.ndarray) -> AudioFrame:
    raw = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    return AudioFrame(raw, sample_rate_hz=SAMPLE_RATE_HZ)


def _frames_with_condition(frames: Sequence[AudioFrame], condition: str) -> tuple[AudioFrame, ...]:
    pcm = b"".join(frame.pcm_s16le for frame in frames)
    samples = np.frombuffer(pcm, dtype=np.int16)
    if condition == "original":
        return (_audio_frame(samples.astype(np.float32) / 32768.0),)
    if condition == "leading_trailing_200ms":
        padding = np.zeros(round(SAMPLE_RATE_HZ * 0.2), dtype=np.int16)
        samples = np.concatenate((padding, samples, padding))
    elif condition.startswith("leading_") or condition.startswith("trailing_"):
        milliseconds = int(condition.split("_")[1].removesuffix("ms"))
        padding = np.zeros(round(SAMPLE_RATE_HZ * milliseconds / 1000), dtype=np.int16)
        samples = (
            np.concatenate((padding, samples))
            if condition.startswith("leading")
            else np.concatenate((samples, padding))
        )
    elif condition == "onset_trimmed_100ms":
        float_samples = samples.astype(np.float32) / 32768.0
        window = round(SAMPLE_RATE_HZ * 0.01)
        rms_values = [
            float(np.sqrt(np.mean(chunk * chunk)))
            for chunk in np.array_split(float_samples, max(1, len(float_samples) // window))
            if len(chunk)
        ]
        threshold = max(0.001, max(rms_values, default=0.0) * 0.10)
        onset = next(
            (index * window for index, value in enumerate(rms_values) if value >= threshold),
            0,
        )
        padding = np.zeros(round(SAMPLE_RATE_HZ * 0.1), dtype=np.int16)
        samples = np.concatenate((padding, samples[onset:]))
    else:
        raise ValueError(f"unsupported audio condition: {condition}")
    return (_audio_frame(samples.astype(np.float32) / 32768.0),)


def _augment_corpus(
    samples: list[Any],
    *,
    english: SherpaOnnxPiperSynthesizer,
    per_base: int,
    helpers: Any,
) -> list[Any]:
    seed = 50_000
    texts = {
        "media_playback": (
            "music is playing",
            "the video is ready",
            "news is playing",
            "background audio",
        ),
        "assistant_tts_playback": (
            "Jarvis",
            "Jarvis is ready",
            "I am checking the project",
            "The project is ready",
        ),
    }
    for category, category_texts in texts.items():
        for text in category_texts:
            base = (
                np.frombuffer(english.synthesize(text)[0].pcm_s16le, dtype=np.int16).astype(
                    np.float32
                )
                / 32768.0
            )
            for _ in range(per_base):
                samples.append(
                    helpers.Sample(helpers._variant(base, seed, positive=False), category, False)
                )
                seed += 1
    for index in range(max(20, per_base * 4)):
        base = helpers._noise(seed + index)
        samples.append(helpers.Sample(base, "fan_keyboard_noise", False))
    return samples


def _bmo_scores(samples: Sequence[Any], profile: Path) -> list[float]:
    scores: list[float] = []
    for sample in samples:
        detector = PersonalizedMfccDtwWakeWordDetector(profile_path=profile, threshold=2.0)
        raw = _audio_frame(sample.audio).pcm_s16le
        for offset in range(0, len(raw), 3200):
            detector.detected(
                AudioFrame(raw[offset : offset + 3200], sample_rate_hz=SAMPLE_RATE_HZ)
            )
        scores.append(float(detector.last_score))
    return scores


def _gpu_snapshot() -> tuple[float | None, float | None]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None, None
    try:
        memory, temperature = (
            float(value.strip()) for value in result.stdout.splitlines()[0].split(",")
        )
        return memory, temperature
    except (IndexError, TypeError, ValueError):
        return None, None


def _metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    accepted_positive = sum(int(row["accepted"]) for row in positives)
    accepted_negative = sum(int(row["accepted"]) for row in negatives)
    latencies = [float(row["latency_ms"]) for row in rows if row["invoked"]]
    miss_categories: dict[str, int] = {}
    for row in positives:
        if not row["accepted"]:
            category = str(row.get("failure_category") or "unknown")
            miss_categories[category] = miss_categories.get(category, 0) + 1
    false_by_category: dict[str, dict[str, int]] = {}
    for row in negatives:
        bucket = false_by_category.setdefault(
            str(row["category"]), {"attempts": 0, "false_activations": 0}
        )
        bucket["attempts"] += 1
        bucket["false_activations"] += int(row["accepted"])
    ordered = sorted(latencies)
    return {
        "attempts": len(rows),
        "positive_attempts": len(positives),
        "positive_detections": accepted_positive,
        "final_recall": round(accepted_positive / max(1, len(positives)), 4),
        "negative_attempts": len(negatives),
        "false_activations": accepted_negative,
        "final_false_activation_rate": round(accepted_negative / max(1, len(negatives)), 4),
        "false_activations_by_category": false_by_category,
        "miss_categories": miss_categories,
        "verifier_invocations": sum(int(row["invoked"]) for row in rows),
        "warm_latency_ms_p50": round(float(median(latencies)) if latencies else 0.0, 3),
        "warm_latency_ms_p95": round(ordered[min(len(ordered) - 1, round(len(ordered) * 0.95))], 3)
        if ordered
        else 0.0,
    }


def _run(
    samples: Sequence[Any],
    verifications: Sequence[Any],
    *,
    condition: str,
    candidate_mask: Sequence[bool],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for sample, invoke in zip(samples, candidate_mask, strict=True):
        if not invoke:
            rows.append(
                {
                    "category": sample.category,
                    "positive": sample.positive,
                    "invoked": False,
                    "accepted": False,
                }
            )
            continue
        result = verifications[len(rows)]
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "invoked": True,
                "accepted": result.accepted,
                "latency_ms": result.latency_ms,
                "failure_category": result.failure_category,
            }
        )
    return _metrics(rows)


def _parse_model(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or name not in MODEL_METADATA:
        raise ValueError("model must be tiny.en=PATH, base.en=PATH, or small.en=PATH")
    path = Path(raw_path).expanduser()
    if not path.is_dir():
        raise ValueError(f"model directory is missing: {name}")
    return name, path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wakeforge-source", type=Path, required=True)
    parser.add_argument("--english-model", type=Path, required=True)
    parser.add_argument("--english-tokens", type=Path, required=True)
    parser.add_argument("--english-data-dir", type=Path, required=True)
    parser.add_argument("--arabic-model", type=Path, required=True)
    parser.add_argument("--arabic-tokens", type=Path, required=True)
    parser.add_argument("--arabic-data-dir", type=Path, required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--cuda-runtime-path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-base", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--beams", nargs="+", type=int, default=[1, 3, 5])
    parser.add_argument(
        "--hotwords", nargs="+", choices=["none", "jarvis"], default=["none", "jarvis"]
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        default=[
            "original",
            "leading_100ms",
            "leading_200ms",
            "trailing_100ms",
            "trailing_200ms",
            "leading_trailing_200ms",
            "onset_trimmed_100ms",
        ],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    sys.path.insert(0, str(ROOT))
    if args.per_base < 4 or args.epochs < 1 or any(beam not in {1, 3, 5} for beam in args.beams):
        raise ValueError("invalid benchmark bounds")
    helpers = importlib.import_module("scripts.phase_10.compare_wakeforge_backends")
    english = SherpaOnnxPiperSynthesizer(
        model=str(args.english_model),
        tokens=str(args.english_tokens),
        data_dir=str(args.english_data_dir),
    )
    arabic = SherpaOnnxPiperSynthesizer(
        model=str(args.arabic_model),
        tokens=str(args.arabic_tokens),
        data_dir=str(args.arabic_data_dir),
    )
    samples = helpers._build_samples(english=english, arabic=arabic, per_base=args.per_base)
    samples = _augment_corpus(samples, english=english, per_base=args.per_base, helpers=helpers)
    train_samples = helpers._build_samples(
        english=english, arabic=arabic, per_base=max(4, args.per_base // 2)
    )
    models = [_parse_model(value) for value in args.model]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bmo-wake-verifier-") as temporary:
        temporary_root = Path(temporary)
        profile = temporary_root / "mfcc-profile.json"
        references = tuple(
            (_audio_frame(helpers._variant(samples[index].audio, index + 1, positive=True)),)
            for index in range(3)
        )
        profile.write_text(serialize_mfcc_profile(references)[0], encoding="utf-8")
        cascade_module: Any = importlib.import_module("scripts.phase_10.benchmark_wake_cascade")
        cascade_module.comparison_helpers = helpers
        wakeforge, wakeforge_identity = cascade_module._train_wakeforge(
            train_samples,
            samples,
            Path(args.wakeforge_source),
            temporary_root / "wakeforge",
            epochs=args.epochs,
        )
        bmo_scores = _bmo_scores(samples, profile)
        wakeforge_scores = [
            float(wakeforge.infer(sample.audio.astype(np.float32))) for sample in samples
        ]
        vad = SileroVoiceActivityDetector()
        vad_mask = [bool(vad.contains_speech((_audio_frame(sample.audio),))) for sample in samples]
        candidate_masks = {
            "vad_whisper": vad_mask,
            "bmo_mfcc_dtw": [score <= 0.9 for score in bmo_scores],
            "wakeforge": [score >= 0.2 for score in wakeforge_scores],
        }
        output_models: dict[str, Any] = {}
        for model_name, model_path in models:
            load_started = time.perf_counter()
            recognizer = FasterWhisperWakePhraseRecognizer(
                model=str(model_path),
                device=args.device,
                compute_type=args.compute_type,
                cuda_runtime_path=args.cuda_runtime_path,
            )
            load_ms = (time.perf_counter() - load_started) * 1000.0
            verifier = WhisperWakePhraseVerifier(recognizer)
            runs: list[dict[str, Any]] = []
            peak_vram: float | None = None
            peak_temp: float | None = None
            for beam in args.beams:
                for hotword in args.hotwords:
                    recognizer.set_decode_configuration(
                        beam_size=beam, hotwords="Jarvis" if hotword == "jarvis" else None
                    )
                    for condition in args.conditions:
                        memory, temperature = (
                            _gpu_snapshot() if args.device.casefold() != "cpu" else (None, None)
                        )
                        if memory is not None:
                            peak_vram = max(peak_vram or memory, memory)
                        if temperature is not None:
                            peak_temp = max(peak_temp or temperature, temperature)
                        verifications = [
                            verifier.verify(
                                _frames_with_condition((_audio_frame(sample.audio),), condition)
                            )
                            for sample in samples
                        ]
                        for architecture, mask in candidate_masks.items():
                            metrics = _run(
                                samples,
                                verifications,
                                condition=condition,
                                candidate_mask=mask,
                            )
                            runs.append(
                                {
                                    "architecture": architecture,
                                    "condition": condition,
                                    "beam_size": beam,
                                    "hotwords": hotword,
                                    "metrics": metrics,
                                }
                            )
            output_models[model_name] = {
                "model": {**MODEL_METADATA[model_name], **_manifest(model_path)},
                "load_ms": round(load_ms, 3),
                "device": args.device,
                "compute_type": args.compute_type,
                "gpu_vram_bytes": round(peak_vram * 1024 * 1024) if peak_vram is not None else None,
                "gpu_temperature_c": peak_temp,
                "runs": runs,
            }
        eligible = [
            (model_name, run)
            for model_name, result in output_models.items()
            for run in result["runs"]
            if run["metrics"]["final_recall"] >= 0.95
            and run["metrics"]["final_false_activation_rate"] <= 0.005
        ]
        best = max(
            (
                (model_name, run)
                for model_name, result in output_models.items()
                for run in result["runs"]
            ),
            key=lambda item: (
                item[1]["metrics"]["final_recall"],
                -item[1]["metrics"]["final_false_activation_rate"],
                -item[1]["metrics"]["warm_latency_ms_p50"],
            ),
        )
        payload = {
            "schema_version": "phase-10-wake-verifier-optimization/v1",
            "phase": 10,
            "wake_word": "Jarvis",
            "synthetic_only": True,
            "owner_audio_used": False,
            "raw_audio_retained": False,
            "temporary_audio_removed": True,
            "corpus": {
                "attempts": len(samples),
                "positive_attempts": sum(int(sample.positive) for sample in samples),
                "negative_attempts": sum(int(not sample.positive) for sample in samples),
                "categories": sorted({sample.category for sample in samples}),
                "held_out_for_all_experiments": True,
            },
            "candidate_architectures": {
                "vad_whisper": {"candidate": "Silero VAD", "threshold": None},
                "bmo_mfcc_dtw": {"candidate": "BMO MFCC/DTW", "threshold": 0.9},
                "wakeforge": {"candidate": "WakeForge", "threshold": 0.2, **wakeforge_identity},
            },
            "decode_contract": {
                "language": "en",
                "task": "transcribe",
                "condition_on_previous_text": False,
                "without_timestamps": True,
                "temperature": 0.0,
                "prefix_forcing": False,
                "hotword_values": [None, "Jarvis"],
                "beam_sizes": list(args.beams),
                "audio_conditions": list(args.conditions),
            },
            "verifiers": output_models,
            "best_observed": {"model": best[0], **best[1]},
            "operating_point_candidates": len(eligible),
            "winner": best[0] if eligible else "none",
            "decision": "selected" if eligible else "blocked_software_operating_point",
            "owner_enrollment_justified": False,
            "phase_11_boundary": "NOT_STARTED",
        }
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
