"""Train a local synthetic-only openWakeWord classifier for the bare ``Jarvis`` phrase.

The script keeps generated PCM entirely in memory. It uses the pinned local
Piper/Sherpa voice and openWakeWord's shared feature extractor, then writes
only the derived ONNX model and a scalar provenance manifest. It is a bounded
candidate builder, not physical acceptance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import SherpaOnnxPiperSynthesizer

torch: Any = importlib.import_module("torch")
AudioFeatures: Any = importlib.import_module("openwakeword.utils").AudioFeatures

TARGET_SAMPLE_RATE = 16_000
CLIP_SAMPLES = 32_000


def _resample(samples: np.ndarray, source_rate: int) -> np.ndarray:
    target_length = max(1, round(len(samples) * TARGET_SAMPLE_RATE / source_rate))
    positions = np.linspace(0.0, len(samples) - 1, target_length)
    return np.asarray(np.interp(positions, np.arange(len(samples)), samples), dtype=np.float32)


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
    return _fit_clip(_resample(pcm, frames[0].sample_rate_hz))


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


def _build_audio(
    tts: SherpaOnnxPiperSynthesizer,
    texts: tuple[str, ...],
    count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    bases = [_synthesize(tts, text) for text in texts]
    return np.stack([_augment(bases[index % len(bases)], rng) for index in range(count)])


def _train(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    seed: int,
    epochs: int,
    threshold: float,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(labels))
    split = max(1, round(len(order) * 0.8))
    train_ndx, test_ndx = order[:split], order[split:]
    if len(test_ndx) == 0:
        raise ValueError("examples-per-class is too small for a held-out test")
    torch.manual_seed(seed)
    model = torch.nn.Sequential(
        torch.nn.LayerNorm((16, 96)),
        torch.nn.Flatten(),
        torch.nn.Linear(16 * 96, 32),
        torch.nn.ReLU(),
        torch.nn.Linear(32, 1),
        torch.nn.Sigmoid(),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = torch.nn.BCELoss()
    x_train = torch.from_numpy(features[train_ndx])
    y_train = torch.from_numpy(labels[train_ndx, None])
    for _ in range(epochs):
        optimizer.zero_grad()
        loss = loss_fn(model(x_train), y_train)
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        scores = model(torch.from_numpy(features[test_ndx])).squeeze(1).numpy()
    predictions = scores >= threshold
    test_labels = labels[test_ndx].astype(bool)
    positives = test_labels.sum()
    negatives = len(test_labels) - positives
    return {
        "model": model,
        "held_out_examples": len(test_ndx),
        "held_out_recall": round(float((predictions & test_labels).sum() / max(1, positives)), 4),
        "held_out_false_activation_rate": round(
            float((predictions & ~test_labels).sum() / max(1, negatives)), 4
        ),
        "threshold": threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--examples-per-class", type=int, default=96)
    parser.add_argument("--epochs", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--threshold", type=float, default=0.7)
    args = parser.parse_args()
    if args.examples_per_class < 32 or args.epochs < 1 or not 0 < args.threshold < 1:
        raise SystemExit("bounded training requires at least 32 examples per class")
    tts = SherpaOnnxPiperSynthesizer(
        model=str(args.english_tts_model),
        tokens=str(args.english_tts_tokens),
        data_dir=str(args.tts_data_dir),
    )
    rng = np.random.default_rng(args.seed)
    positives = _build_audio(tts, ("Jarvis", "Jarvis.", "Jarvis?"), args.examples_per_class, rng)
    negatives = _build_audio(
        tts,
        ("Hey Jarvis", "Java", "service", "start the music", "good morning"),
        args.examples_per_class,
        rng,
    )
    audio = np.vstack((positives, negatives))
    labels = np.concatenate(
        (np.ones(len(positives), dtype=np.float32), np.zeros(len(negatives), dtype=np.float32))
    )
    features = AudioFeatures(inference_framework="onnx", device="cpu").embed_clips(
        audio, batch_size=32, ncpu=1
    )
    result = _train(features, labels, seed=args.seed, epochs=args.epochs, threshold=args.threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model = result.pop("model")
    model.eval()
    torch.onnx.export(
        model,
        (torch.zeros((1, 16, 96), dtype=torch.float32),),
        args.output,
        input_names=["input"],
        output_names=["output"],
        opset_version=18,
    )
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "phase-10-jarvis-wake-model/v1",
        "model_name": "jarvis-openwakeword-synthetic-v0.1",
        "target_phrase": "Jarvis",
        "engine": "openwakeword==0.6.0 ONNX shared feature extractor",
        "training": {
            "method": "synthetic local Piper/Sherpa speech plus deterministic augmentation",
            "examples_per_class": args.examples_per_class,
            "epochs": args.epochs,
            "seed": args.seed,
            "user_recordings": False,
            "raw_audio_retained": False,
            **result,
        },
        "artifact": {
            "path": "BMO/VoiceModels/jarvis-openwakeword-synthetic-v0.1.onnx",
            "sha256": digest,
            "format": "ONNX",
        },
        "license": {
            "derived_model": "local owner-generated artifact; not redistributed",
            "feature_extractor": "Apache-2.0 openWakeWord",
            "synthetic_tts": "existing local voice artifact terms apply",
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": str(args.output), "sha256": digest, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
