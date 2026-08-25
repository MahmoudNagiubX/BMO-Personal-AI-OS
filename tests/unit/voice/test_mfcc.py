from __future__ import annotations

import json
from pathlib import Path

import numpy
import pytest

from personal_ai_os.voice.adapters import PersonalizedMfccDtwWakeWordDetector
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import (
    derive_mfcc_templates,
    extract_mfcc,
    normalized_subsequence_dtw_distance,
    serialize_mfcc_profile,
)


def _phrase(variant: int, *, seconds: float = 0.8) -> AudioFrame:
    sample_count = int(16_000 * seconds)
    time = numpy.arange(sample_count, dtype=numpy.float32) / 16_000.0
    frequencies = (320.0, 410.0, 510.0)
    signal = 0.35 * numpy.sin(2 * numpy.pi * frequencies[0] * time) + 0.18 * numpy.sin(
        2 * numpy.pi * (frequencies[1] * 2) * time
    )
    signal *= 0.85 + 0.05 * variant
    return AudioFrame(numpy.clip(signal * 32767, -32768, 32767).astype(numpy.int16).tobytes())


def _negative() -> AudioFrame:
    sample_count = int(16_000 * 0.8)
    time = numpy.arange(sample_count, dtype=numpy.float32) / 16_000.0
    signal = 0.42 * numpy.sin(2 * numpy.pi * 880.0 * time)
    return AudioFrame(numpy.clip(signal * 32767, -32768, 32767).astype(numpy.int16).tobytes())


def test_mfcc_frontend_is_weight_free_and_finite() -> None:
    features = extract_mfcc(_phrase(0).pcm_s16le)
    assert features.ndim == 2
    assert features.shape[1] == 13
    assert bool(numpy.isfinite(features).all())


def test_subsequence_dtw_matches_phrase_inside_following_command() -> None:
    template = extract_mfcc(_phrase(0).pcm_s16le)
    command = AudioFrame(_phrase(0).pcm_s16le + _negative().pcm_s16le)
    candidate = extract_mfcc(command.pcm_s16le)
    negative = extract_mfcc(_negative().pcm_s16le)
    assert normalized_subsequence_dtw_distance(candidate, template) < 0.42
    assert normalized_subsequence_dtw_distance(negative, template) > 0.42


def test_profile_contains_only_derived_templates_and_detector_is_streaming(
    tmp_path: Path,
) -> None:
    flattened = tuple((_phrase(index),) for index in range(3))
    profile = tmp_path / "jarvis-mfcc-profile.json"
    profile_text, digest = serialize_mfcc_profile(flattened)
    profile.write_text(profile_text, encoding="utf-8")
    payload = json.loads(profile.read_text(encoding="utf-8"))
    assert payload["profile_sha256"] == digest
    assert payload["raw_audio_retained"] is False
    assert "pcm" not in profile.read_text(encoding="utf-8").casefold()

    detector = PersonalizedMfccDtwWakeWordDetector(
        profile_path=profile,
        threshold=0.42,
        min_template_matches=2,
    )
    raw = _phrase(0).pcm_s16le + _negative().pcm_s16le
    detected = False
    for offset in range(0, len(raw), 3200):
        detected = detector.detected(AudioFrame(raw[offset : offset + 3200])) or detected
    assert detected is True
    detector.reset()
    assert detector.detected(_negative()) is False


def test_profile_integrity_is_checked(tmp_path: Path) -> None:
    recordings = tuple((_phrase(index),) for index in range(3))
    profile = tmp_path / "profile.json"
    profile_text, _ = serialize_mfcc_profile(recordings)
    profile.write_text(profile_text, encoding="utf-8")
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["templates"][0][0][0] += 1.0
    profile.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="profile is invalid"):
        PersonalizedMfccDtwWakeWordDetector(profile_path=profile)


def test_profile_requires_three_to_four_recordings() -> None:
    with pytest.raises(ValueError, match="requires 3 or 4"):
        derive_mfcc_templates(((_phrase(0),),))
