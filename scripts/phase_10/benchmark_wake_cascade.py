"""Benchmark the bounded two-stage local wake cascade.

The runner creates a held-out synthetic corpus in a temporary directory,
trains/evaluates candidate stages, invokes local Whisper only for candidate
windows, and emits scalar JSON.  PCM and temporary model files are removed at
process exit; no owner audio or transcript is written to the output.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
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
    FasterWhisperRecognizer,
    PersonalizedMfccDtwWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
)
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import serialize_mfcc_profile
from personal_ai_os.voice.wake_cascade import WhisperWakePhraseVerifier

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "phase-10-wake-cascade/v1"
SAMPLE_RATE_HZ = 16_000
WAKEFORGE_REVISION = "1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7"
OVOS_PLUGIN_REVISION = "a9df8ca94453c160eddd99381ba8c95576f74026"
OVOS_LISTENER_REVISION = "4d44ce62d4b90eb59be95dff563a4b1893d31ca3"
Sample = Any
comparison_helpers: Any = None
MODEL_METADATA = {
    "small": {
        "repository": "Systran/faster-whisper-small",
        "revision": "536b0662742c02347bc0e980a01041f333bce120",
        "license": "MIT",
    },
    "medium": {
        "repository": "Systran/faster-whisper-medium",
        "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f",
        "license": "MIT",
    },
}


def _load_comparison_helpers() -> Any:
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    return importlib.import_module("scripts.phase_10.compare_wakeforge_backends")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_manifest(path: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix()
        size = file_path.stat().st_size
        files[relative] = {"bytes": size, "sha256": _sha256(file_path)}
        total_bytes += size
    return {"basename": path.name, "bytes": total_bytes, "files": files}


def _gpu_snapshot() -> tuple[float | None, float | None]:
    """Read only aggregate GPU memory/temperature scalars when nvidia-smi exists."""

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
    if result.returncode != 0 or not result.stdout.strip():
        return None, None
    try:
        memory, temperature = (
            float(value.strip()) for value in result.stdout.splitlines()[0].split(",")
        )
        return memory, temperature
    except (TypeError, ValueError):
        return None, None


def _model_key(name: str) -> str:
    for key in MODEL_METADATA:
        if key in name.casefold():
            return key
    raise ValueError("verifier name must identify a supported small or medium model")


def _parse_verifier(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError("verifier must use name=local-model-directory")
    path = Path(raw_path).expanduser()
    if not path.is_dir():
        raise ValueError(f"verifier model directory is missing: {name}")
    return name.strip(), path


def _audio_frame(audio: np.ndarray) -> AudioFrame:
    raw = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    return AudioFrame(raw, sample_rate_hz=SAMPLE_RATE_HZ)


def _make_profile(samples: Sequence[Sample], path: Path) -> None:
    references = tuple(
        (_audio_frame(comparison_helpers._variant(samples[index].audio, index + 1, positive=True)),)
        for index in range(3)
    )
    profile_text, _ = serialize_mfcc_profile(references)
    path.write_text(profile_text, encoding="utf-8")


def _bmo_score(profile: Path, sample: Sample) -> tuple[float, float]:
    detector = PersonalizedMfccDtwWakeWordDetector(profile_path=profile, threshold=2.0)
    raw = _audio_frame(sample.audio).pcm_s16le
    started = time.perf_counter()
    for offset in range(0, len(raw), 3200):
        detector.detected(AudioFrame(raw[offset : offset + 3200], sample_rate_hz=SAMPLE_RATE_HZ))
    return detector.last_score, (time.perf_counter() - started) * 1000.0


def _train_wakeforge(
    train_samples: Sequence[Sample],
    test_samples: Sequence[Sample],
    source: Path,
    output: Path,
    *,
    epochs: int,
) -> tuple[Any, dict[str, Any]]:
    train_dir = output / "train"
    test_dir = output / "test"
    train_data = comparison_helpers._write_dataset(train_samples, train_dir, "train")
    test_data = comparison_helpers._write_dataset(test_samples, test_dir, "test")
    sys.path.insert(0, str(source))
    inference = importlib.import_module("ww_trainer.inference")
    trainer_module = importlib.import_module("ww_trainer.trainer")
    trainer = trainer_module.WakeWordTrainer(
        arch="gru",
        featurizer="",
        wake_word="Jarvis",
        device="cpu",
        export_onnx=True,
        featurizer_type="mfcc",
        losses_cfg=[{"name": "bce"}],
        n_mfcc=40,
        n_mels=40,
        n_fft=400,
        hop_length=160,
        hidden_dim=128,
        seed=42,
    )
    started = time.perf_counter()
    trainer.train(
        output,
        train_data,
        test_data,
        epochs=epochs,
        batch_size=16,
        lr=1e-3,
        patience=3,
        save_best=True,
        pca_every=0,
        tsne_every=0,
        umap_every=0,
        rppl_every=0,
        aug_prob=0.0,
        spec_augment=False,
        use_mixup=False,
    )
    head = output / "best_f1.onnx"
    extractor = output / "best_f1_featurizer.onnx"
    if not head.is_file() or not extractor.is_file():
        raise RuntimeError("WakeForge training did not produce both ONNX artifacts")
    inferencer = inference.OnnxWakeWordInferencer(
        str(extractor), str(head), sample_rate=SAMPLE_RATE_HZ, device="cpu"
    )
    return inferencer, {
        "revision": WAKEFORGE_REVISION,
        "plugin_revision": OVOS_PLUGIN_REVISION,
        "listener_revision": OVOS_LISTENER_REVISION,
        "classifier_sha256": _sha256(head),
        "feature_extractor_sha256": _sha256(extractor),
        "classifier_bytes": head.stat().st_size,
        "feature_extractor_bytes": extractor.stat().st_size,
        "training_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def _score_candidates(
    samples: Sequence[Sample], profile: Path, wakeforge: Any
) -> dict[str, list[dict[str, Any]]]:
    scores: dict[str, list[dict[str, Any]]] = {"bmo_mfcc_dtw": [], "wakeforge": []}
    for sample in samples:
        bmo_score, bmo_latency = _bmo_score(profile, sample)
        started = time.perf_counter()
        wakeforge_score = float(wakeforge.infer(sample.audio.astype(np.float32)))
        wakeforge_latency = (time.perf_counter() - started) * 1000.0
        for name, score, latency in (
            ("bmo_mfcc_dtw", bmo_score, bmo_latency),
            ("wakeforge", wakeforge_score, wakeforge_latency),
        ):
            scores[name].append(
                {
                    "category": sample.category,
                    "positive": sample.positive,
                    "score": float(score),
                    "latency_ms": latency,
                }
            )
    return scores


def _verifier_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    latency = [float(row["verifier_latency_ms"]) for row in rows if row["verifier_invoked"]]
    false_by_category: dict[str, dict[str, int]] = {}
    for row in negatives:
        category = str(row["category"])
        bucket = false_by_category.setdefault(category, {"attempts": 0, "false_accepts": 0})
        bucket["attempts"] += 1
        bucket["false_accepts"] += int(row["final_accept"])
    return {
        "attempts": len(rows),
        "positive_attempts": len(positives),
        "positive_detections": sum(int(row["final_accept"]) for row in positives),
        "final_recall": round(
            sum(int(row["final_accept"]) for row in positives) / max(1, len(positives)), 4
        ),
        "negative_attempts": len(negatives),
        "false_activations": sum(int(row["final_accept"]) for row in negatives),
        "final_false_activation_rate": round(
            sum(int(row["final_accept"]) for row in negatives) / max(1, len(negatives)), 4
        ),
        "false_activations_by_category": false_by_category,
        "verifier_invocations": sum(int(row["verifier_invoked"]) for row in rows),
        "candidate_to_verification_latency_ms_p50": round(
            float(median(latency)) if latency else 0.0, 3
        ),
        "candidate_to_verification_latency_ms_p95": round(
            sorted(latency)[min(len(latency) - 1, round(len(latency) * 0.95))] if latency else 0.0,
            3,
        ),
        "hard_phonetic_false_accepts": sum(
            int(row["final_accept"]) for row in negatives if row["category"] == "hard_phonetic"
        ),
    }


def _run_verifier(
    samples: Sequence[Sample],
    candidate_rows: Sequence[dict[str, Any]] | None,
    verifier: WhisperWakePhraseVerifier,
    *,
    require_candidate: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        candidate = True if candidate_rows is None else bool(candidate_rows[index]["candidate"])
        started = time.perf_counter()
        result = (
            verifier.verify((_audio_frame(sample.audio),))
            if (candidate or not require_candidate)
            else None
        )
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "candidate": candidate,
                "verifier_invoked": result is not None,
                "verifier_accepted": bool(result.accepted) if result is not None else False,
                "verifier_latency_ms": result.latency_ms if result is not None else 0.0,
                "candidate_to_verification_wall_ms": (time.perf_counter() - started) * 1000.0,
                "final_accept": bool(result.accepted) if result is not None else False,
            }
        )
    return rows


def _candidate_sweep(
    rows: Sequence[dict[str, Any]],
    verifier_rows_by_threshold: dict[float, list[dict[str, Any]]],
    thresholds: Sequence[float],
    *,
    lower_is_better: bool,
) -> list[dict[str, Any]]:
    sweep: list[dict[str, Any]] = []
    for threshold in thresholds:
        candidate_rows = [
            {
                **row,
                "candidate": (
                    float(row["score"]) <= threshold
                    if lower_is_better
                    else float(row["score"]) >= threshold
                ),
            }
            for row in rows
        ]
        final_rows = verifier_rows_by_threshold[threshold]
        positive = [row for row in final_rows if row["positive"]]
        negative = [row for row in final_rows if not row["positive"]]
        final_metrics = _verifier_metrics(final_rows)
        sweep.append(
            {
                "threshold": threshold,
                "candidate_recall": round(
                    sum(int(row["candidate"]) for row in candidate_rows if row["positive"])
                    / max(1, len(positive)),
                    4,
                ),
                "candidate_false_activation_rate": round(
                    sum(int(row["candidate"]) for row in candidate_rows if not row["positive"])
                    / max(1, len(negative)),
                    4,
                ),
                "candidate_volume": sum(int(row["candidate"]) for row in candidate_rows),
                "verifier_invocations": sum(int(row["verifier_invoked"]) for row in final_rows),
                **final_metrics,
            }
        )
    return sweep


def _scalar_thresholds(start: float, stop: float, step: float) -> tuple[float, ...]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 4))
        current += step
    return tuple(values)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wakeforge-source", type=Path, required=True)
    parser.add_argument("--english-model", type=Path, required=True)
    parser.add_argument("--english-tokens", type=Path, required=True)
    parser.add_argument("--english-data-dir", type=Path, required=True)
    parser.add_argument("--arabic-model", type=Path, required=True)
    parser.add_argument("--arabic-tokens", type=Path, required=True)
    parser.add_argument("--arabic-data-dir", type=Path, required=True)
    parser.add_argument("--verifier", action="append", required=True)
    parser.add_argument("--verifier-device", default="cpu")
    parser.add_argument("--verifier-compute-type", default="int8")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-base", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    global comparison_helpers
    args = _parse_args()
    if args.per_base < 4 or args.epochs < 1:
        raise ValueError("per-base must be at least 4 and epochs must be positive")
    comparison_helpers = _load_comparison_helpers()
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
    train_samples = comparison_helpers._build_samples(
        english=english, arabic=arabic, per_base=max(4, args.per_base // 2)
    )
    samples = comparison_helpers._build_samples(
        english=english, arabic=arabic, per_base=args.per_base
    )
    verifier_specs = [_parse_verifier(value) for value in args.verifier]
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bmo-wake-cascade-") as temporary:
        temporary_root = Path(temporary)
        profile = temporary_root / "mfcc-profile.json"
        _make_profile(samples, profile)
        train_output = temporary_root / "wakeforge"
        wakeforge, wakeforge_identity = _train_wakeforge(
            train_samples, samples, args.wakeforge_source, train_output, epochs=args.epochs
        )
        candidate_scores = _score_candidates(samples, profile, wakeforge)
        bmo_thresholds = _scalar_thresholds(0.20, 1.00, 0.05)
        wakeforge_thresholds = _scalar_thresholds(0.20, 1.00, 0.05)
        verifier_output: dict[str, Any] = {}
        for verifier_name, verifier_path in verifier_specs:
            key = _model_key(verifier_name)
            load_started = time.perf_counter()
            recognizer = FasterWhisperRecognizer(
                model=str(verifier_path),
                device=args.verifier_device,
                compute_type=args.verifier_compute_type,
            )
            load_ms = (time.perf_counter() - load_started) * 1000.0
            verifier = WhisperWakePhraseVerifier(recognizer)
            variant: dict[str, Any] = {
                "model": {
                    **MODEL_METADATA[key],
                    **_artifact_manifest(verifier_path),
                },
                "load_ms": round(load_ms, 3),
                "device": args.verifier_device,
                "compute_type": args.verifier_compute_type,
            }
            try:
                import psutil

                process = psutil.Process(os.getpid())
                cpu_before = process.cpu_times().user + process.cpu_times().system
                rss_before = process.memory_info().rss
            except ImportError:
                process = None
                cpu_before = 0.0
                rss_before = 0
            verifier_results = []
            peak_memory_mb: float | None = None
            peak_temperature_c: float | None = None
            for sample in samples:
                verifier_results.append(verifier.verify((_audio_frame(sample.audio),)))
                memory_mb, temperature_c = (
                    _gpu_snapshot() if args.verifier_device.casefold() != "cpu" else (None, None)
                )
                if memory_mb is not None:
                    peak_memory_mb = max(peak_memory_mb or memory_mb, memory_mb)
                if temperature_c is not None:
                    peak_temperature_c = max(peak_temperature_c or temperature_c, temperature_c)
            if process is not None:
                cpu_after = process.cpu_times().user + process.cpu_times().system
                variant["process_cpu_ms"] = round((cpu_after - cpu_before) * 1000.0, 3)
                variant["ram_rss_delta_bytes"] = max(0, process.memory_info().rss - rss_before)
            variant["gpu_vram_bytes"] = (
                round(peak_memory_mb * 1024 * 1024) if peak_memory_mb is not None else None
            )
            variant["gpu_temperature_c"] = peak_temperature_c
            for candidate_name, thresholds, lower_is_better in (
                ("bmo_mfcc_dtw", bmo_thresholds, True),
                ("wakeforge", wakeforge_thresholds, False),
            ):
                base_rows = candidate_scores[candidate_name]
                all_final_rows: dict[float, list[dict[str, Any]]] = {}
                for threshold in thresholds:
                    candidate_rows = [
                        {
                            **row,
                            "candidate": (
                                row["score"] <= threshold
                                if lower_is_better
                                else row["score"] >= threshold
                            ),
                        }
                        for row in base_rows
                    ]
                    all_final_rows[threshold] = [
                        {
                            "category": sample.category,
                            "positive": sample.positive,
                            "candidate": bool(candidate_rows[index]["candidate"]),
                            "verifier_invoked": bool(candidate_rows[index]["candidate"]),
                            "verifier_accepted": (
                                verifier_results[index].accepted
                                if candidate_rows[index]["candidate"]
                                else False
                            ),
                            "verifier_latency_ms": (
                                verifier_results[index].latency_ms
                                if candidate_rows[index]["candidate"]
                                else 0.0
                            ),
                            "final_accept": (
                                verifier_results[index].accepted
                                if candidate_rows[index]["candidate"]
                                else False
                            ),
                        }
                        for index, sample in enumerate(samples)
                    ]
                variant.setdefault("cascades", {})[candidate_name] = {
                    "threshold_sweep": _candidate_sweep(
                        base_rows,
                        all_final_rows,
                        thresholds,
                        lower_is_better=lower_is_better,
                    ),
                    "best_observed": max(
                        (
                            _verifier_metrics(rows) | {"threshold": threshold}
                            for threshold, rows in all_final_rows.items()
                        ),
                        key=lambda item: (
                            float(item["final_recall"]) >= 0.95
                            and float(item["final_false_activation_rate"]) <= 0.005,
                            float(item["final_recall"]),
                            -float(item["final_false_activation_rate"]),
                        ),
                    ),
                }
            vad = SileroVoiceActivityDetector()
            control_rows: list[dict[str, Any]] = []
            for index, sample in enumerate(samples):
                frame = _audio_frame(sample.audio)
                speech = vad.contains_speech((frame,))
                result = verifier_results[index] if speech else None
                control_rows.append(
                    {
                        "category": sample.category,
                        "positive": sample.positive,
                        "candidate": speech,
                        "verifier_invoked": result is not None,
                        "verifier_accepted": bool(result.accepted) if result else False,
                        "verifier_latency_ms": result.latency_ms if result else 0.0,
                        "final_accept": bool(result.accepted) if result else False,
                    }
                )
            variant["vad_whisper_control"] = _verifier_metrics(control_rows)
            verifier_output[verifier_name] = variant
        payload = {
            "schema_version": SCHEMA,
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
            "candidate_stages": {
                "bmo_mfcc_dtw": {
                    "engine": "BMO-owned MFCC/normalized-subsequence-DTW",
                    "score_direction": "lower_is_better",
                    "thresholds": list(bmo_thresholds),
                },
                "wakeforge": {
                    "engine": "WakeForge locally constructed MFCC + GRU ONNX",
                    "score_direction": "higher_is_better",
                    "thresholds": list(wakeforge_thresholds),
                    **wakeforge_identity,
                },
            },
            "verifiers": verifier_output,
            "winner": "none",
            "decision": "blocked_software_operating_point",
            "owner_enrollment_justified": False,
            "phase_11_boundary": "NOT_STARTED",
        }
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
