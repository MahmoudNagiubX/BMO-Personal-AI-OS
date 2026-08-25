"""BMO-owned MFCC extraction and bounded DTW matching primitives.

The implementation intentionally has no pretrained wake-word or embedding
weights.  NumPy is imported lazily because voice dependencies are optional.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from personal_ai_os.voice.contracts import AudioFrame


@dataclass(frozen=True, slots=True)
class MfccConfig:
    """Deterministic, bounded MFCC frontend parameters."""

    sample_rate_hz: int = 16_000
    frame_length: int = 400
    hop_length: int = 160
    n_fft: int = 512
    n_mels: int = 26
    n_mfcc: int = 13


DEFAULT_MFCC_CONFIG = MfccConfig()
PROFILE_SCHEMA = "phase-10-personalized-mfcc-dtw/v1"


def _numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ImportError as exc:
        raise RuntimeError("numpy is required for personalized MFCC wake detection") from exc


def extract_mfcc(
    pcm_s16le: bytes,
    *,
    config: MfccConfig = DEFAULT_MFCC_CONFIG,
) -> Any:
    """Extract a finite MFCC matrix from ephemeral mono 16-bit PCM."""

    if config.sample_rate_hz != 16_000:
        raise ValueError("personalized MFCC wake detection requires 16 kHz audio")
    if not pcm_s16le or len(pcm_s16le) % 2:
        raise ValueError("MFCC input must contain complete PCM samples")
    numpy = _numpy()
    samples = numpy.frombuffer(pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    samples = samples / numpy.float32(32768.0)
    if samples.size < config.frame_length:
        samples = numpy.pad(samples, (0, config.frame_length - samples.size))
    samples = numpy.asarray(samples, dtype=numpy.float32)
    samples = numpy.concatenate((samples[:1], samples[1:] - numpy.float32(0.97) * samples[:-1]))
    frame_count = 1 + max(0, (samples.size - config.frame_length) // config.hop_length)
    required = config.frame_length + (frame_count - 1) * config.hop_length
    if samples.size < required:
        samples = numpy.pad(samples, (0, required - samples.size))
    indices = (
        numpy.arange(config.frame_length)[None, :]
        + config.hop_length * numpy.arange(frame_count)[:, None]
    )
    frames = samples[indices] * numpy.hanning(config.frame_length).astype(numpy.float32)
    spectrum = numpy.fft.rfft(frames, n=config.n_fft, axis=1)
    power = (numpy.abs(spectrum) ** 2) / numpy.float32(config.n_fft)
    filters = _mel_filterbank(config, numpy)
    mel = numpy.maximum(power @ filters.T, numpy.float32(1e-10))
    log_mel = numpy.log(mel)
    basis = numpy.cos(
        (numpy.pi / config.n_mels)
        * (numpy.arange(config.n_mfcc)[:, None])
        * (numpy.arange(config.n_mels)[None, :] + numpy.float32(0.5))
    ).astype(numpy.float32)
    features = log_mel @ basis.T
    return numpy.asarray(features, dtype=numpy.float32)


def _mel_filterbank(config: MfccConfig, numpy: Any) -> Any:
    """Build a Slaney-style triangular mel filterbank deterministically."""

    low_hz = 20.0
    high_hz = min(7600.0, config.sample_rate_hz / 2.0)

    def hz_to_mel(value: float) -> float:
        return 1127.0 * math.log1p(value / 700.0)

    def mel_to_hz(value: float) -> float:
        return 700.0 * math.expm1(value / 1127.0)

    points = numpy.linspace(hz_to_mel(low_hz), hz_to_mel(high_hz), config.n_mels + 2)
    frequencies = numpy.asarray([mel_to_hz(float(point)) for point in points])
    bins = numpy.floor((config.n_fft + 1) * frequencies / config.sample_rate_hz).astype(int)
    filters = numpy.zeros((config.n_mels, config.n_fft // 2 + 1), dtype=numpy.float32)
    for index in range(config.n_mels):
        left, center, right = bins[index : index + 3]
        if center > left:
            filters[index, left:center] = numpy.linspace(0.0, 1.0, center - left)
        if right > center:
            filters[index, center:right] = numpy.linspace(1.0, 0.0, right - center)
    return filters


def normalized_subsequence_dtw_distance(candidate: Any, template: Any) -> float:
    """Return a bounded normalized cosine DTW distance for a subsequence."""

    return normalized_subsequence_dtw_distance_from(
        candidate,
        template,
        max_start_frames=None,
    )


def normalized_subsequence_dtw_distance_from(
    candidate: Any,
    template: Any,
    *,
    max_start_frames: int | None,
) -> float:
    """Match a template in a bounded prefix of a streaming candidate."""

    if getattr(candidate, "ndim", 0) != 2 or getattr(template, "ndim", 0) != 2:
        raise ValueError("MFCC matrices must be two-dimensional")
    if candidate.shape[1] != template.shape[1] or not candidate.size or not template.size:
        return float("inf")
    numpy = _numpy()
    template_length = int(template.shape[0])
    candidate_length = int(candidate.shape[0])
    if candidate_length <= int(template_length * 1.35):
        return _normalized_dtw(candidate, template, numpy)
    lower = max(8, int(template_length * 0.75))
    upper = min(candidate_length, max(lower, int(template_length * 1.25)))
    stride = max(1, template_length // 8)
    best = float("inf")
    for window_length in range(lower, upper + 1, stride):
        last_start = candidate_length - window_length
        if max_start_frames is not None:
            last_start = min(last_start, max_start_frames)
        for start in range(0, last_start + 1, stride):
            best = min(
                best,
                _normalized_dtw(candidate[start : start + window_length], template, numpy),
            )
    return best


def _normalized_dtw(candidate: Any, template: Any, numpy: Any) -> float:
    candidate = _normalize_features(candidate, numpy)
    template = _normalize_features(template, numpy)
    candidate_norm = numpy.linalg.norm(candidate, axis=1, keepdims=True)
    template_norm = numpy.linalg.norm(template, axis=1, keepdims=True)
    similarity = (template @ candidate.T) / numpy.maximum(
        template_norm * candidate_norm.T, numpy.float32(1e-6)
    )
    costs = numpy.clip(1.0 - similarity, 0.0, 2.0)
    rows, columns = template.shape[0], candidate.shape[0]
    distance = numpy.full((rows + 1, columns + 1), numpy.float32("inf"))
    distance[0, 0] = 0.0
    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            distance[row, column] = costs[row - 1, column - 1] + min(
                distance[row - 1, column - 1],
                distance[row - 1, column],
                distance[row, column - 1],
            )
    return float(distance[rows, columns] / max(rows, columns))


def _normalize_features(features: Any, numpy: Any) -> Any:
    # Normalize each coefficient across the candidate window so spectral
    # shape remains discriminative while bounded gain changes are reduced.
    mean = features.mean(axis=0, keepdims=True)
    deviation = features.std(axis=0, keepdims=True)
    return (features - mean) / numpy.maximum(deviation, numpy.float32(1e-4))


def derive_mfcc_templates(
    recordings: tuple[tuple[AudioFrame, ...], ...],
    *,
    config: MfccConfig = DEFAULT_MFCC_CONFIG,
) -> tuple[Any, ...]:
    """Convert bounded recordings into derived templates and discard PCM."""

    if not 3 <= len(recordings) <= 4:
        raise ValueError("personalized MFCC enrollment requires 3 or 4 recordings")
    templates: list[Any] = []
    for recording in recordings:
        if not recording:
            raise ValueError("enrollment recordings must not be empty")
        if any(
            frame.sample_rate_hz != config.sample_rate_hz or frame.channels != 1
            for frame in recording
        ):
            raise ValueError("enrollment audio format is unsupported")
        pcm = b"".join(frame.pcm_s16le for frame in recording)
        templates.append(extract_mfcc(pcm, config=config))
    return tuple(templates)


def serialize_mfcc_profile(
    recordings: tuple[tuple[AudioFrame, ...], ...],
    *,
    config: MfccConfig = DEFAULT_MFCC_CONFIG,
) -> tuple[str, str]:
    """Return a derived-template profile for an outer persistence boundary."""

    templates = derive_mfcc_templates(recordings, config=config)
    body: dict[str, Any] = {
        "schema_version": PROFILE_SCHEMA,
        "wake_word": "Jarvis",
        "sample_rate_hz": config.sample_rate_hz,
        "feature_config": asdict(config),
        "template_count": len(templates),
        "templates": [template.tolist() for template in templates],
        "raw_audio_retained": False,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body["profile_sha256"] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(body, sort_keys=True) + "\n", str(body["profile_sha256"])


def read_mfcc_profile(output_path: Path) -> tuple[MfccConfig, tuple[Any, ...]]:
    """Load and verify a derived-template-only profile."""

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("personalized MFCC profile is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("personalized MFCC profile is invalid")
    expected_hash = payload.pop("profile_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not isinstance(expected_hash, str) or hashlib.sha256(canonical).hexdigest() != expected_hash:
        raise ValueError("personalized MFCC profile integrity check failed")
    if (
        payload.get("schema_version") != PROFILE_SCHEMA
        or payload.get("wake_word") != "Jarvis"
        or payload.get("sample_rate_hz") != 16_000
        or payload.get("raw_audio_retained") is not False
    ):
        raise ValueError("personalized MFCC profile identity is not accepted")
    feature_config = payload.get("feature_config")
    if not isinstance(feature_config, dict):
        raise ValueError("personalized MFCC profile feature configuration is missing")
    config = MfccConfig(**feature_config)
    raw_templates = payload.get("templates")
    if not isinstance(raw_templates, list) or not 3 <= len(raw_templates) <= 4:
        raise ValueError("personalized MFCC profile must contain 3 or 4 templates")
    numpy = _numpy()
    templates = tuple(numpy.asarray(template, dtype=numpy.float32) for template in raw_templates)
    if any(template.ndim != 2 or template.shape[1] != config.n_mfcc for template in templates):
        raise ValueError("personalized MFCC profile template shape is invalid")
    if payload.get("template_count") != len(templates):
        raise ValueError("personalized MFCC profile template count is invalid")
    return config, templates


__all__ = [
    "DEFAULT_MFCC_CONFIG",
    "PROFILE_SCHEMA",
    "MfccConfig",
    "derive_mfcc_templates",
    "extract_mfcc",
    "normalized_subsequence_dtw_distance",
    "read_mfcc_profile",
    "serialize_mfcc_profile",
]
