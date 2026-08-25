"""Compare BMO MFCC/DTW with a license-audited WakeForge MFCC model.

This is an evaluation-only script.  WakeForge is loaded from an explicitly
provided local checkout and is not a production dependency.  All generated
PCM and temporary model/profile files live under a temporary directory and
are removed when the process exits.  The output contains scalar metrics only.

The comparison intentionally uses the exact ``Jarvis`` phrase and locally
generated Piper speech.  It does not download Hugging Face datasets, use
cloud TTS, use voice conversion, or use a pre-exported feature extractor.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import (
    PersonalizedMfccDtwWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
)
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import serialize_mfcc_profile

SAMPLE_RATE_HZ = 16_000
SCHEMA = "phase-10-wake-backend-comparison/v1"
WAKEFORGE_REVISION = "1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7"
OVOS_PLUGIN_REVISION = "a9df8ca94453c160eddd99381ba8c95576f74026"
OVOS_LISTENER_REVISION = "4d44ce62d4b90eb59be95dff563a4b1893d31ca3"


@dataclass(frozen=True)
class Sample:
    audio: np.ndarray
    category: str
    positive: bool


def _resample(frame: AudioFrame) -> np.ndarray:
    values = np.frombuffer(frame.pcm_s16le, dtype=np.int16).astype(np.float32)
    if frame.sample_rate_hz != SAMPLE_RATE_HZ:
        target = max(1, round(len(values) * SAMPLE_RATE_HZ / frame.sample_rate_hz))
        values = np.interp(
            np.linspace(0, len(values) - 1, target),
            np.arange(len(values)),
            values,
        ).astype(np.float32)
    return np.asarray(np.clip(values / 32768.0, -1.0, 1.0), dtype=np.float32)


def _synthesize(tts: SherpaOnnxPiperSynthesizer, text: str) -> np.ndarray:
    frames = tuple(tts.synthesize(text))
    if not frames:
        raise RuntimeError("local TTS returned no audio")
    return _resample(frames[0])


def _variant(base: np.ndarray, seed: int, *, positive: bool) -> np.ndarray:
    """Apply deterministic bounded variation without retaining a source file."""

    rng = np.random.default_rng(seed)
    audio = base.astype(np.float32, copy=True)
    audio *= (0.55, 0.72, 0.9, 1.0, 1.12, 0.8)[seed % 6]
    if seed % 3 == 0:
        rate = (0.94, 1.0, 1.06)[seed % 3]
        target = max(1, round(len(audio) / rate))
        audio = np.interp(
            np.linspace(0, len(audio) - 1, target),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)
    if seed % 4 == 0:
        audio += rng.normal(0.0, 0.0035 if positive else 0.006, len(audio)).astype(np.float32)
    leading = int((seed % 5) * SAMPLE_RATE_HZ * 0.025)
    trailing = int(((seed + 2) % 4) * SAMPLE_RATE_HZ * 0.02)
    return np.clip(
        np.concatenate(
            (np.zeros(leading, dtype=np.float32), audio, np.zeros(trailing, dtype=np.float32))
        ),
        -1.0,
        1.0,
    )


def _noise(seed: int, *, seconds: float = 1.2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.0025, round(SAMPLE_RATE_HZ * seconds)).astype(np.float32)


def _build_samples(
    *,
    english: SherpaOnnxPiperSynthesizer,
    arabic: SherpaOnnxPiperSynthesizer,
    per_base: int,
) -> list[Sample]:
    bases: dict[str, tuple[SherpaOnnxPiperSynthesizer, tuple[str, ...], bool]] = {
        "positive": (
            english,
            (
                "Jarvis",
                "Jarvis open VS Code",
                "Jarvis check the project",
                "Jarvis tell me the status",
                "Jarvis continue",
                "Jarvis listen",
            ),
            True,
        ),
        "normal_english": (
            english,
            (
                "open VS Code",
                "check the project",
                "tell me the status",
                "good morning",
                "continue the work",
                "read the status",
            ),
            False,
        ),
        "hard_phonetic": (
            english,
            (
                "Jervis is a name",
                "the jar is visible",
                "hey service",
                "jar is full",
                "Harvis is here",
                "Hey Jarvis",
            ),
            False,
        ),
        "arabic": (
            arabic,
            (
                "افتح المحرر",
                "تحقق من المشروع",
                "صباح الخير",
                "أخبرني بالحالة",
                "استمر في العمل",
                "لا تستمع",
            ),
            False,
        ),
        "mixed": (
            english,
            ("افتح VS Code", "تحقق من the project", "قل لي the status", "ابدأ listening"),
            False,
        ),
        "background_conversation": (
            english,
            (
                "I am speaking normally",
                "please continue the meeting",
                "what is left today",
                "the project is ready",
            ),
            False,
        ),
    }
    samples: list[Sample] = []
    seed = 100
    for category, (tts, texts, positive) in bases.items():
        for text in texts:
            base = _synthesize(tts, text)
            for _ in range(per_base):
                samples.append(Sample(_variant(base, seed, positive=positive), category, positive))
                seed += 1
    for index in range(max(20, per_base * 5)):
        samples.append(Sample(_noise(seed + index), "silence_noise", False))
    return samples


def _write_dataset(
    samples: Iterable[Sample], directory: Path, prefix: str
) -> list[tuple[str, str]]:
    soundfile = importlib.import_module("soundfile")
    write = soundfile.write
    directory.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str]] = []
    for index, sample in enumerate(samples):
        path = directory / f"{prefix}-{index:04d}.wav"
        write(path, sample.audio, SAMPLE_RATE_HZ, subtype="PCM_16")
        rows.append((str(path), "1" if sample.positive else "0"))
    return rows


def _bmo_detect(profile: Path, sample: Sample) -> tuple[bool, float, float]:
    detector = PersonalizedMfccDtwWakeWordDetector(profile_path=profile)
    started = time.perf_counter()
    raw = np.clip(sample.audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    detected = False
    for offset in range(0, len(raw), 3200):
        detected = detector.detected(
            AudioFrame(raw[offset : offset + 3200], sample_rate_hz=SAMPLE_RATE_HZ)
        )
        if detected:
            break
    return detected, (time.perf_counter() - started) * 1000.0, detector.last_score


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    by_category: dict[str, dict[str, int]] = {}
    for row in negatives:
        category = str(row["category"])
        current = by_category.setdefault(category, {"attempts": 0, "false_activations": 0})
        current["attempts"] += 1
        current["false_activations"] += int(row["detected"])
    score_by_category: dict[str, dict[str, float]] = {}
    for category in sorted({str(row["category"]) for row in rows}):
        values = sorted(float(row["score"]) for row in rows if row["category"] == category)
        score_by_category[category] = {
            "min": round(values[0], 6),
            "median": round(float(median(values)), 6),
            "max": round(values[-1], 6),
        }
    latencies = [float(row["latency_ms"]) for row in rows]
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, round(len(ordered) * 0.95))]
    return {
        "attempts": len(rows),
        "positive_attempts": len(positives),
        "positive_detections": sum(int(row["detected"]) for row in positives),
        "recall": round(sum(int(row["detected"]) for row in positives) / max(1, len(positives)), 4),
        "negative_attempts": len(negatives),
        "false_activations": sum(int(row["detected"]) for row in negatives),
        "false_activation_rate": round(
            sum(int(row["detected"]) for row in negatives) / max(1, len(negatives)), 4
        ),
        "false_activations_by_category": by_category,
        "score_by_category": score_by_category,
        "latency_ms_median": round(float(median(latencies)), 3),
        "latency_ms_p95": round(float(p95), 3),
        "latency_ms_max": round(max(latencies), 3),
        "score_min": round(min(float(row["score"]) for row in rows), 6),
        "score_max": round(max(float(row["score"]) for row in rows), 6),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_bmo(samples: list[Sample], profile: Path) -> tuple[dict[str, Any], float]:
    references = tuple(
        (
            AudioFrame(
                np.clip(
                    _variant(samples[index].audio, index + 1, positive=True) * 32767.0,
                    -32768,
                    32767,
                )
                .astype(np.int16)
                .tobytes(),
                sample_rate_hz=SAMPLE_RATE_HZ,
            ),
        )
        for index in range(3)
    )
    profile_text, _ = serialize_mfcc_profile(references)
    profile.write_text(profile_text, encoding="utf-8")
    try:
        import psutil

        process = psutil.Process(os.getpid())
        cpu_before = process.cpu_times().user + process.cpu_times().system
        rss_before = process.memory_info().rss
    except ImportError:
        process = None
        cpu_before = 0.0
        rss_before = 0
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for sample in samples:
        detected, latency, score = _bmo_detect(profile, sample)
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "detected": detected,
                "latency_ms": latency,
                "score": score,
            }
        )
    metrics = _metrics(rows)
    metrics["profile_bytes"] = profile.stat().st_size
    if process is not None:
        cpu_after = process.cpu_times().user + process.cpu_times().system
        metrics["cpu_process_ms"] = round((cpu_after - cpu_before) * 1000.0, 2)
        metrics["ram_rss_delta_bytes"] = max(0, process.memory_info().rss - rss_before)
    return metrics, (time.perf_counter() - started) * 1000.0


def _run_wakeforge(
    samples: list[Sample],
    train_data: list[tuple[str, str]],
    test_data: list[tuple[str, str]],
    output: Path,
    source: Path,
    epochs: int,
) -> tuple[dict[str, Any], float]:
    import sys

    sys.path.insert(0, str(source))
    inference = importlib.import_module("ww_trainer.inference")
    trainer_module = importlib.import_module("ww_trainer.trainer")
    inferencer_type = inference.OnnxWakeWordInferencer
    trainer_type = trainer_module.WakeWordTrainer

    trainer = trainer_type(
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
    training_started = time.perf_counter()
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
    model_load_started = time.perf_counter()
    inferencer = inferencer_type(
        str(extractor), str(head), sample_rate=SAMPLE_RATE_HZ, device="cpu"
    )
    model_load_ms = (time.perf_counter() - model_load_started) * 1000.0
    try:
        import psutil

        process = psutil.Process(os.getpid())
        cpu_before = process.cpu_times().user + process.cpu_times().system
        rss_before = process.memory_info().rss
    except ImportError:
        process = None
        cpu_before = 0.0
        rss_before = 0
    rows: list[dict[str, Any]] = []
    for sample in samples:
        infer_started = time.perf_counter()
        score = float(inferencer.infer(sample.audio.astype(np.float32)))
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "detected": score >= 0.5,
                "latency_ms": (time.perf_counter() - infer_started) * 1000.0,
                "score": score,
            }
        )
    metrics = _metrics(rows)
    metrics["threshold"] = 0.5
    metrics["classifier_bytes"] = head.stat().st_size
    metrics["feature_extractor_bytes"] = extractor.stat().st_size
    metrics["classifier_sha256"] = _sha256(head)
    metrics["feature_extractor_sha256"] = _sha256(extractor)
    metrics["model_load_ms"] = round(model_load_ms, 2)
    metrics["training_ms"] = round((model_load_started - training_started) * 1000.0, 2)
    if process is not None:
        cpu_after = process.cpu_times().user + process.cpu_times().system
        metrics["cpu_process_ms"] = round((cpu_after - cpu_before) * 1000.0, 2)
        metrics["ram_rss_delta_bytes"] = max(0, process.memory_info().rss - rss_before)
    return metrics, (time.perf_counter() - training_started) * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wakeforge-source", type=Path, required=True)
    parser.add_argument("--english-model", type=Path, required=True)
    parser.add_argument("--english-tokens", type=Path, required=True)
    parser.add_argument("--english-data-dir", type=Path, required=True)
    parser.add_argument("--arabic-model", type=Path, required=True)
    parser.add_argument("--arabic-tokens", type=Path, required=True)
    parser.add_argument("--arabic-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-base", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()
    if args.per_base < 4 or args.epochs < 1:
        raise SystemExit("per-base must be >=4 and epochs must be positive")
    if not (args.wakeforge_source / "ww_trainer").is_dir():
        raise SystemExit("WakeForge source checkout is missing ww_trainer")

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
    with tempfile.TemporaryDirectory(prefix="bmo-wake-compare-") as raw_temp:
        temp = Path(raw_temp)
        train_samples = _build_samples(
            english=english, arabic=arabic, per_base=max(4, args.per_base // 2)
        )
        test_samples = _build_samples(english=english, arabic=arabic, per_base=args.per_base)
        train_data = _write_dataset(train_samples, temp / "train", "train")
        test_data = _write_dataset(test_samples, temp / "test", "test")
        bmo, bmo_startup_ms = _run_bmo(test_samples, temp / "bmo-profile.json")
        wakeforge, wakeforge_startup_ms = _run_wakeforge(
            test_samples,
            train_data,
            test_data,
            temp / "wakeforge",
            args.wakeforge_source,
            args.epochs,
        )
        report = {
            "schema_version": SCHEMA,
            "wake_word": "Jarvis",
            "synthetic_only": True,
            "owner_audio_used": False,
            "raw_audio_retained": False,
            "temporary_audio_removed": True,
            "source_policy": {
                "hugging_face_datasets_used": False,
                "cloud_tts_used": False,
                "voice_conversion_used": False,
                "preexported_feature_artifact_used": False,
                "local_piper_speech": True,
            },
            "wakeforge": {
                "revision": WAKEFORGE_REVISION,
                "license": "Apache-2.0",
                "feature_frontend": "locally constructed WakeForge MFCC extractor",
                "runtime": "WakeForge ONNX extractor + classifier; CPU",
                "metrics": wakeforge,
                "startup_ms": round(wakeforge_startup_ms, 2),
            },
            "ovos_reference": {
                "wakeforge_plugin_revision": OVOS_PLUGIN_REVISION,
                "wakeforge_plugin_license": "Apache-2.0",
                "dinkum_listener_revision": OVOS_LISTENER_REVISION,
                "dinkum_listener_license": "Apache-2.0",
                "integrated": False,
                "audio_frontend_review": (
                    "reference only; no far-field or raw-audio retention changes"
                ),
            },
            "bmo": {
                "engine": "BMO-owned MFCC/normalized-subsequence-DTW",
                "feature_frontend": "NumPy MFCC; no pretrained wake or embedding weights",
                "metrics": bmo,
                "startup_ms": round(bmo_startup_ms, 2),
            },
            "local_tts_provenance": {
                "english_model": {
                    "basename": args.english_model.name,
                    "sha256": _sha256(args.english_model),
                    "terms": (
                        "Piper model card: lessac Blizzard 2013 dataset; "
                        "license URL recorded locally"
                    ),
                },
                "arabic_model": {
                    "basename": args.arabic_model.name,
                    "sha256": _sha256(args.arabic_model),
                    "terms": (
                        "Piper model card: kareem Arabic TTS dataset; license URL recorded locally"
                    ),
                },
            },
            "limitations": [
                "synthetic local speech is not owner or far-field acceptance",
                (
                    "single installed local voice per language; accent and microphone "
                    "diversity require later owner evidence"
                ),
                (
                    "WakeForge default remote datasets and optional cloud/voice-conversion "
                    "paths were not used"
                ),
            ],
            "owner_enrollment_justified": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": SCHEMA,
                "bmo": bmo,
                "wakeforge": wakeforge,
                "owner_enrollment_justified": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
