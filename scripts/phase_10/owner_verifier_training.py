"""BMO-owned OpenWakeWord owner-verifier training primitives.

The pinned upstream helper hard-codes ``threshold=0.5`` while extracting
positive reference features.  This module keeps the upstream feature and
classifier implementations, but makes the candidate threshold an explicit,
calibrated input.
"""

from __future__ import annotations

import importlib
import pickle
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 1_280


def _required_callable(module: object, name: str) -> Callable[..., Any]:
    value = getattr(module, name, None)
    if not callable(value):
        raise RuntimeError(f"OpenWakeWord helper is unavailable: {name}")
    return cast(Callable[..., Any], value)


@dataclass(frozen=True, slots=True)
class BaseCandidateDiagnostics:
    """Scalar diagnostics for one temporary owner clip."""

    maximum_score: float
    candidate_frames: int
    threshold: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "maximum_score": round(self.maximum_score, 7),
            "candidate_frames": self.candidate_frames,
            "threshold": round(self.threshold, 7),
        }


def score_base_clip(
    model: Any,
    samples: np.ndarray,
    model_name: str,
    *,
    threshold: float,
) -> BaseCandidateDiagnostics:
    """Score a PCM16 clip using the production 80 ms streaming frame size."""

    if not 0.0 <= threshold <= 1.0:
        raise ValueError("base candidate threshold must be between 0 and 1")
    model.reset()
    maximum = 0.0
    candidate_frames = 0
    bounded = np.asarray(samples, dtype=np.int16).reshape(-1)
    for offset in range(0, len(bounded) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        prediction = model.predict(bounded[offset : offset + FRAME_SAMPLES])
        score = float(prediction.get(model_name, 0.0))
        maximum = max(maximum, score)
        candidate_frames += int(score >= threshold)
    return BaseCandidateDiagnostics(maximum, candidate_frames, threshold)


def extract_positive_features(
    clip: str | Path,
    model: Any,
    model_name: str,
    *,
    base_candidate_invoke_threshold: float,
    variations: int = 5,
) -> np.ndarray:
    """Use the pinned OWW extractor with BMO's calibrated candidate threshold."""

    if not 0.0 <= base_candidate_invoke_threshold <= 1.0:
        raise ValueError("base candidate threshold must be between 0 and 1")
    custom_verifier_model = importlib.import_module("openwakeword.custom_verifier_model")
    get_reference_clip_features = _required_callable(
        custom_verifier_model, "get_reference_clip_features"
    )
    features = np.asarray(
        get_reference_clip_features(
            str(clip),
            model,
            model_name,
            threshold=base_candidate_invoke_threshold,
            N=variations,
        )
    )
    if features.ndim != 3 or features.shape[0] == 0:
        raise ValueError("calibrated base candidate produced no positive features")
    return features


def extract_negative_features(clips: list[str | Path], model: Any, model_name: str) -> np.ndarray:
    """Extract bounded negative features using the pinned OWW negative policy."""

    custom_verifier_model = importlib.import_module("openwakeword.custom_verifier_model")
    get_reference_clip_features = _required_callable(
        custom_verifier_model, "get_reference_clip_features"
    )
    features = np.vstack(
        [
            get_reference_clip_features(str(clip), model, model_name, threshold=0.0, N=1)
            for clip in clips
        ]
    )
    if features.ndim != 3 or features.shape[0] == 0:
        raise ValueError("negative reference clips produced no features")
    return features


def train_calibrated_verifier(
    positive_clips: list[str | Path],
    negative_clips: list[str | Path],
    *,
    base_model_path: Path,
    output_path: Path,
    base_candidate_invoke_threshold: float,
) -> dict[str, int | float]:
    """Train a pickle compatible with ``openwakeword.Model`` custom verifiers."""

    openwakeword = importlib.import_module("openwakeword")
    custom_verifier_model = importlib.import_module("openwakeword.custom_verifier_model")
    model_factory = _required_callable(openwakeword, "Model")
    train_verifier_model = _required_callable(custom_verifier_model, "train_verifier_model")
    model = model_factory(
        wakeword_models=[str(base_model_path)],
        inference_framework="onnx",
        vad_threshold=0.0,
    )
    model_name = base_model_path.stem
    positive_features = np.vstack(
        [
            extract_positive_features(
                clip,
                model,
                model_name,
                base_candidate_invoke_threshold=base_candidate_invoke_threshold,
            )
            for clip in positive_clips
        ]
    )
    negative_features = extract_negative_features(negative_clips, model, model_name)
    labels = np.array([1] * len(positive_features) + [0] * len(negative_features), dtype=np.int8)
    verifier = train_verifier_model(np.vstack((positive_features, negative_features)), labels)
    with output_path.open("wb") as handle:
        pickle.dump(verifier, handle)
    return {
        "positive_feature_windows": len(positive_features),
        "negative_feature_windows": len(negative_features),
        "base_candidate_invoke_threshold": base_candidate_invoke_threshold,
    }


__all__ = [
    "BaseCandidateDiagnostics",
    "extract_negative_features",
    "extract_positive_features",
    "score_base_clip",
    "train_calibrated_verifier",
]
