"""Measure the Rhasspy Hey Jarvis detector on local, scalar-only inputs.

Optional positive and negative WAV paths are read only into bounded process
memory.  The default run is a deterministic negative smoke stream; it makes
no acoustic recall claim and writes no audio or result files.
"""

from __future__ import annotations

import argparse
import struct
import time
import wave
from pathlib import Path
from typing import Any

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.rhasspy_wake import (
    DEFAULT_REFRACTORY_SECONDS,
    DEFAULT_THRESHOLD,
    DEFAULT_TRIGGER_LEVEL,
    RhasspyHeyJarvisDetector,
)

FRAME_BYTES = 2_560  # 80 ms at 16 kHz mono PCM16, matching SoundDeviceBackend.
DEFAULT_NEGATIVE_SECONDS = 10.0


def _deterministic_noise(seconds: float) -> bytes:
    sample_count = max(1, round(seconds * 16_000))
    return b"".join(
        struct.pack("<h", ((index * 7919) % 65_536) - 32_768) for index in range(sample_count)
    )


def _read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as source:
        if (
            source.getframerate() != 16_000
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
        ):
            raise ValueError("WAV must be 16 kHz mono PCM16")
        payload = source.readframes(source.getnframes())
    if not payload:
        raise ValueError("WAV is empty")
    return payload


def _run_stream(
    detector: RhasspyHeyJarvisDetector,
    pcm_s16le: bytes,
    probabilities: list[float],
) -> dict[str, Any]:
    started = time.perf_counter()
    detected = False
    for offset in range(0, len(pcm_s16le), FRAME_BYTES):
        frame = pcm_s16le[offset : offset + FRAME_BYTES]
        detected = detector.detected(AudioFrame(frame)) or detected
    return {
        "detected": detected,
        "peak_probability": round(max(probabilities, default=0.0), 6),
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "audio_seconds": round(len(pcm_s16le) / 2 / 16_000, 3),
        "raw_audio_retained": False,
    }


def _measure(paths: list[Path], *, expected_positive: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in paths:
        probabilities: list[float] = []
        detector = RhasspyHeyJarvisDetector(
            threshold=DEFAULT_THRESHOLD,
            trigger_level=DEFAULT_TRIGGER_LEVEL,
            refractory_seconds=DEFAULT_REFRACTORY_SECONDS,
            probability_observer=probabilities.append,
        )
        try:
            result = _run_stream(detector, _read_wav(path), probabilities)
        finally:
            detector.close()
        result.update({"expected_positive": expected_positive, "input": "local_wav"})
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-wav", action="append", type=Path, default=[])
    parser.add_argument("--negative-wav", action="append", type=Path, default=[])
    parser.add_argument("--negative-seconds", type=float, default=DEFAULT_NEGATIVE_SECONDS)
    args = parser.parse_args()
    if args.negative_seconds <= 0:
        raise ValueError("negative smoke duration must be positive")

    results = _measure(args.positive_wav, expected_positive=True)
    if args.negative_wav:
        results.extend(_measure(args.negative_wav, expected_positive=False))
    else:
        probabilities: list[float] = []
        detector = RhasspyHeyJarvisDetector(
            threshold=DEFAULT_THRESHOLD,
            trigger_level=DEFAULT_TRIGGER_LEVEL,
            refractory_seconds=DEFAULT_REFRACTORY_SECONDS,
            probability_observer=probabilities.append,
        )
        try:
            result = _run_stream(
                detector,
                _deterministic_noise(args.negative_seconds),
                probabilities,
            )
        finally:
            detector.close()
        result.update({"expected_positive": False, "input": "deterministic_in_memory_noise"})
        results.append(result)

    positives = [result for result in results if result["expected_positive"]]
    negatives = [result for result in results if not result["expected_positive"]]
    detections = sum(bool(result["detected"]) for result in positives)
    false_activations = sum(bool(result["detected"]) for result in negatives)
    hours = sum(float(result["audio_seconds"]) for result in negatives) / 3_600.0
    status = "measured" if positives else "negative_smoke_only"
    recall = detections / len(positives) if positives else None
    far = false_activations / len(negatives) if negatives else 0.0
    faph = false_activations / hours if hours else 0.0
    print(
        "RHASSPY_BENCHMARK_PASS "
        f"status={status} positive={detections}/{len(positives)} "
        f"recall={recall if recall is not None else 'not_measured'} "
        f"negative_false_activations={false_activations}/{len(negatives)} "
        f"far={far:.4f} faph={faph:.4f} raw_audio_retained=false",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
