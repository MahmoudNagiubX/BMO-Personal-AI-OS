"""Build a synthetic-only local microWakeWord candidate for bare ``Jarvis``.

The trainer follows the official Apache-2.0 microWakeWord training entrypoint,
but intentionally uses only locally generated Piper/Sherpa speech and bounded
deterministic augmentation.  All generated WAV files, feature maps, training
checkpoints, and intermediate reports live under a temporary directory and are
deleted before the command returns.  Only the requested TFLite model, runtime
config, and sanitized provenance manifest survive.

This is a candidate builder.  It cannot establish the ASUS TUF physical
reliability gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import SherpaOnnxPiperSynthesizer

TARGET_SAMPLE_RATE = 16_000
CLIP_SAMPLES = 24_000
SHA256_PATTERN = r"^[0-9a-f]{40}$"


def _fit_clip(samples: np.ndarray) -> np.ndarray:
    if len(samples) >= CLIP_SAMPLES:
        start = (len(samples) - CLIP_SAMPLES) // 2
        return samples[start : start + CLIP_SAMPLES].astype(np.int16)
    return np.pad(samples, (0, CLIP_SAMPLES - len(samples))).astype(np.int16)


def _synthesize(tts: SherpaOnnxPiperSynthesizer, text: str) -> np.ndarray:
    frames = tts.synthesize(text)
    if len(frames) != 1:
        raise RuntimeError("synthetic TTS returned an unexpected frame count")
    pcm = np.frombuffer(frames[0].pcm_s16le, dtype=np.int16).astype(np.float32)
    if frames[0].sample_rate_hz != TARGET_SAMPLE_RATE:
        target_length = max(1, round(len(pcm) * TARGET_SAMPLE_RATE / frames[0].sample_rate_hz))
        positions = np.linspace(0.0, len(pcm) - 1, target_length)
        pcm = np.asarray(np.interp(positions, np.arange(len(pcm)), pcm), dtype=np.float32)
    return _fit_clip(pcm)


def _augment(base: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    gain = float(rng.uniform(0.42, 1.05))
    scaled = base.astype(np.float32) * gain
    speed = float(rng.uniform(0.86, 1.18))
    target_length = max(1, round(len(scaled) / speed))
    positions = np.linspace(0.0, len(scaled) - 1, target_length)
    resized = np.asarray(np.interp(positions, np.arange(len(scaled)), scaled), dtype=np.float32)
    resized = _fit_clip(resized)
    noise_rms = float(rng.uniform(0.0, 0.018)) * 32768.0
    noise = rng.normal(0.0, noise_rms, size=resized.shape)
    offset = int(rng.integers(0, 1600))
    shifted = np.roll(resized + noise, offset)
    return np.clip(shifted, -32768, 32767).astype(np.int16)


def _write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(TARGET_SAMPLE_RATE)
        output.writeframes(samples.tobytes())


def _write_class_audio(
    directory: Path,
    tts: SherpaOnnxPiperSynthesizer,
    texts: tuple[str, ...],
    count: int,
    rng: np.random.Generator,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    bases = [_synthesize(tts, text) for text in texts]
    for index in range(count):
        _write_wav(directory / f"sample-{index:04d}.wav", _augment(bases[index % len(bases)], rng))


def _generate_feature_sets(
    *,
    source: Path,
    audio_directory: Path,
    output_directory: Path,
    seed: int,
) -> None:
    sys.path.insert(0, str(source))
    clips_module: Any = importlib.import_module("microwakeword.audio.clips")
    spectrograms_module: Any = importlib.import_module("microwakeword.audio.spectrograms")
    mmap_module: Any = importlib.import_module("mmap_ninja.ragged")
    Clips: Any = clips_module.Clips
    SpectrogramGeneration: Any = spectrograms_module.SpectrogramGeneration
    RaggedMmap: Any = mmap_module.RaggedMmap

    clips = Clips(
        str(audio_directory),
        "*.wav",
        random_split_seed=seed,
        split_count=0.2,
        trim_zeros=False,
    )
    for split, repeat, slide_frames in (
        ("training", 2, 10),
        ("validation", 1, 10),
        ("testing", 1, 1),
    ):
        source_split = {"training": "train", "validation": "validation", "testing": "test"}[split]
        spectrograms = SpectrogramGeneration(
            clips=clips,
            augmenter=None,
            step_ms=10,
            slide_frames=slide_frames,
        )
        target = output_directory / split / "synthetic_mmap"
        target.parent.mkdir(parents=True, exist_ok=True)
        RaggedMmap.from_generator(
            out_dir=str(target),
            sample_generator=spectrograms.spectrogram_generator(
                split=source_split,
                repeat=repeat,
            ),
            batch_size=100,
            verbose=False,
        )


def _training_config(work: Path, positive: Path, negative: Path, steps: int) -> Path:
    import yaml  # type: ignore[import-untyped]

    config: dict[str, Any] = {
        "window_step_ms": 10,
        "train_dir": str(work / "trained_models" / "wakeword"),
        "features": [
            {
                "features_dir": str(positive),
                "sampling_weight": 2.0,
                "penalty_weight": 1.0,
                "truth": True,
                "truncation_strategy": "truncate_start",
                "type": "mmap",
            },
            {
                "features_dir": str(negative),
                "sampling_weight": 8.0,
                "penalty_weight": 1.0,
                "truth": False,
                "truncation_strategy": "random",
                "type": "mmap",
            },
        ],
        "training_steps": [steps],
        "positive_class_weight": [1],
        "negative_class_weight": [8],
        "learning_rates": [0.001],
        "batch_size": 32,
        "time_mask_max_size": [0],
        "time_mask_count": [0],
        "freq_mask_max_size": [0],
        "freq_mask_count": [0],
        "eval_step_interval": max(100, min(500, steps // 4)),
        "clip_duration_ms": 1500,
        "target_minimization": 0.9,
        "minimization_metric": "loss",
        "maximization_metric": "average_viable_recall",
    }
    path = work / "training_parameters.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _run_official_training(source: Path, config: Path, work: Path) -> Path:
    trained = work / "trained_models" / "wakeword"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source) + os.pathsep + env.get("PYTHONPATH", "")
    command = [
        sys.executable,
        "-m",
        "microwakeword.model_train_eval",
        f"--training_config={config}",
        "--train",
        "1",
        "--restore_checkpoint",
        "0",
        "--test_tf_nonstreaming",
        "0",
        "--test_tflite_nonstreaming",
        "0",
        "--test_tflite_nonstreaming_quantized",
        "0",
        "--test_tflite_streaming",
        "0",
        "--test_tflite_streaming_quantized",
        "1",
        "--use_weights",
        "best_weights",
        "mixednet",
        "--pointwise_filters",
        "64,64,64,64",
        "--repeat_in_block",
        "1,1,1,1",
        "--mixconv_kernel_sizes",
        "[5], [7,11], [9,15], [23]",
        "--residual_connection",
        "0,0,0,0",
        "--first_conv_filters",
        "32",
        "--first_conv_kernel_size",
        "5",
        "--stride",
        "3",
    ]
    subprocess.run(command, cwd=work, env=env, check=True)
    model = trained / "tflite_stream_state_internal_quant" / "stream_state_internal_quant.tflite"
    if not model.is_file():
        raise RuntimeError(
            "official microWakeWord trainer did not produce a quantized TFLite model"
        )
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-source", type=Path, required=True)
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--examples-per-class", type=int, default=48)
    parser.add_argument("--training-steps", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args()
    if len(args.upstream_commit) != 40 or any(
        c not in "0123456789abcdef" for c in args.upstream_commit
    ):
        raise SystemExit("--upstream-commit must be a full lowercase Git SHA")
    if args.examples_per_class < 24 or args.training_steps < 100 or not 0 < args.threshold < 1:
        raise SystemExit("bounded microWakeWord training requires >=24 examples and >=100 steps")
    if args.output_model.parent != args.output_config.parent:
        raise SystemExit("output model and runtime config must share a directory")
    source = args.upstream_source.resolve()
    if not (source / "LICENSE").is_file():
        raise SystemExit("official microWakeWord source LICENSE is missing")

    tts = SherpaOnnxPiperSynthesizer(
        model=str(args.english_tts_model),
        tokens=str(args.english_tts_tokens),
        data_dir=str(args.tts_data_dir),
    )
    with tempfile.TemporaryDirectory(prefix="bmo-microwakeword-") as temporary:
        work = Path(temporary)
        rng = np.random.default_rng(args.seed)
        positive_audio = work / "positive_audio"
        negative_audio = work / "negative_audio"
        _write_class_audio(
            positive_audio, tts, ("Jarvis", "Jarvis.", "Jarvis?"), args.examples_per_class, rng
        )
        _write_class_audio(
            negative_audio,
            tts,
            ("Hey Jarvis", "Java", "Jervis", "service", "start the music", "good morning"),
            args.examples_per_class,
            rng,
        )
        positive_features = work / "positive_features"
        negative_features = work / "negative_features"
        _generate_feature_sets(
            source=source,
            audio_directory=positive_audio,
            output_directory=positive_features,
            seed=args.seed,
        )
        _generate_feature_sets(
            source=source,
            audio_directory=negative_audio,
            output_directory=negative_features,
            seed=args.seed + 1,
        )
        training_config = _training_config(
            work, positive_features, negative_features, args.training_steps
        )
        model = _run_official_training(source, training_config, work)

        args.output_model.parent.mkdir(parents=True, exist_ok=True)
        args.output_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model, args.output_model)
        config = {
            "type": "micro",
            "wake_word": "Jarvis",
            "author": "BMO local synthetic candidate",
            "model": args.output_model.name,
            "trained_languages": ["en"],
            "version": 2,
            "micro": {
                "probability_cutoff": args.threshold,
                "feature_step_size": 10,
                "sliding_window_size": 5,
                "tensor_arena_size": 100000,
            },
        }
        args.output_config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    digest = hashlib.sha256(args.output_model.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "phase-10-jarvis-wake-model/v1",
        "model_name": "jarvis-microwakeword-synthetic-v0.1",
        "target_phrase": "Jarvis",
        "engine": "pymicro-wakeword==2.4.1; official microWakeWord trainer",
        "training": {
            "method": (
                "official Apache-2.0 microWakeWord trainer with synthetic local "
                "Piper/Sherpa speech and deterministic augmentation"
            ),
            "examples_per_class": args.examples_per_class,
            "training_steps": args.training_steps,
            "seed": args.seed,
            "user_recordings": False,
            "raw_audio_retained": False,
            "datasets": "none; no public or mixed-license audio dataset used",
            "upstream_commit": args.upstream_commit,
            "physical_acceptance": "pending",
        },
        "artifact": {
            "path": "BMO/VoiceModels/jarvis-microwakeword-synthetic-v0.1.tflite",
            "sha256": digest,
            "format": "TFLite",
        },
        "license": {
            "trainer": "Apache-2.0 microWakeWord",
            "runtime": "Apache-2.0 pymicro-wakeword",
            "derived_model": "local owner-generated artifact; not redistributed",
            "synthetic_tts": "existing local voice artifact terms apply",
        },
        "status": "candidate_not_physically_accepted",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"model": str(args.output_model), "sha256": digest, "status": manifest["status"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
