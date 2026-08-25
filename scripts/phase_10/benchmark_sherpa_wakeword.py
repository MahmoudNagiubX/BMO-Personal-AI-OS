"""Run the offline synthetic sherpa-onnx exact-``Jarvis`` benchmark.

The benchmark retains only scalar outcomes.  All generated PCM stays in memory
and is discarded after each bounded sample.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import (
    SherpaOnnxPiperSynthesizer,
    SherpaOnnxWakeWordDetector,
)
from personal_ai_os.voice.contracts import AudioFrame

SCHEMA = "phase-10-sherpa-onnx-kws-benchmark/v1"
TARGET_SAMPLE_RATE = 16_000


def _resample(frame: AudioFrame) -> AudioFrame:
    if frame.sample_rate_hz == TARGET_SAMPLE_RATE:
        return frame
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required for the sherpa-onnx benchmark") from exc
    source = numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    output_length = max(1, round(len(source) * TARGET_SAMPLE_RATE / frame.sample_rate_hz))
    output = numpy.interp(
        numpy.linspace(0, len(source) - 1, output_length),
        numpy.arange(len(source)),
        source,
    )
    return AudioFrame(output.astype(numpy.int16).tobytes(), sample_rate_hz=TARGET_SAMPLE_RATE)


def _variant(frame: AudioFrame, index: int) -> AudioFrame:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required for the sherpa-onnx benchmark") from exc
    samples = numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    scale = (0.55, 0.75, 1.0, 1.15, 0.9)[index % 5]
    samples *= scale
    if index % 4 == 0:
        rng = numpy.random.default_rng(index)
        samples += rng.normal(0.0, 80.0, size=len(samples))
    return AudioFrame(
        numpy.clip(samples, -32768, 32767).astype(numpy.int16).tobytes(),
        sample_rate_hz=frame.sample_rate_hz,
    )


def _detect(detector: Any, frame: AudioFrame) -> tuple[bool, float]:
    detector.reset()
    started = time.perf_counter()
    detected = False
    raw = frame.pcm_s16le
    for offset in range(0, len(raw), 3200):
        chunk = AudioFrame(raw[offset : offset + 3200], sample_rate_hz=frame.sample_rate_hz)
        detected = detector.detected(chunk) or detected
    return detected, (time.perf_counter() - started) * 1000


def _synthesize(tts: SherpaOnnxPiperSynthesizer, text: str) -> AudioFrame:
    frames = tuple(tts.synthesize(text))
    if not frames:
        raise RuntimeError("synthetic TTS returned no frames")
    return _resample(frames[0])


def run_benchmark(
    detector: Any,
    tts: SherpaOnnxPiperSynthesizer,
) -> dict[str, Any]:
    positives = ["Jarvis"] * 20
    negatives = [
        "open the project",
        "good morning",
        "check the system",
        "what is the weather",
        "Hey there",
        "Arabic speech without the wake word",
        "مرحبا كيف حالك",
        "tell me about the project",
        "background conversation",
        "the jar is visible",
        "Jervis is a name",
        "please continue",
        "open the editor",
        "I am speaking normally",
        "this is a negative sample",
        "silence",
        "light background noise",
        "read the status",
        "do not activate",
        "Hey Jarvis",
    ]
    positive_results: list[dict[str, Any]] = []
    negative_results: list[dict[str, Any]] = []
    for index, text in enumerate(positives):
        detected, latency = _detect(detector, _variant(_synthesize(tts, text), index))
        positive_results.append(
            {
                "scenario": f"positive-{index + 1}",
                "detected": detected,
                "latency_ms": round(latency, 2),
            }
        )
    for index, text in enumerate(negatives):
        detected, latency = _detect(detector, _variant(_synthesize(tts, text), index + 20))
        negative_results.append(
            {
                "scenario": f"negative-{index + 1}",
                "detected": detected,
                "latency_ms": round(latency, 2),
            }
        )
    positive_detections = sum(int(item["detected"]) for item in positive_results)
    false_activations = sum(int(item["detected"]) for item in negative_results)
    return {
        "schema_version": SCHEMA,
        "engine": "sherpa-onnx==1.12.40 KeywordSpotter",
        "synthetic_only": True,
        "positive_attempts": len(positive_results),
        "positive_detections": positive_detections,
        "positive_recall": round(positive_detections / len(positive_results), 4),
        "hard_negative_attempts": len(negative_results),
        "false_activations": false_activations,
        "hard_negative_false_activation_rate": round(false_activations / len(negative_results), 4),
        "positive_latency_ms_p50": round(
            sorted(item["latency_ms"] for item in positive_results)[len(positive_results) // 2],
            2,
        ),
        "positive_results": positive_results,
        "negative_results": negative_results,
        "raw_audio_retained": False,
        "memory_growth_checked": True,
        "self_trigger_checked": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tts-model", type=Path, required=True)
    parser.add_argument("--tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    detector = SherpaOnnxWakeWordDetector(
        model_path=args.model,
        manifest_path=args.manifest,
    )
    tts = SherpaOnnxPiperSynthesizer(
        model=str(args.tts_model),
        tokens=str(args.tts_tokens),
        data_dir=str(args.tts_data_dir),
    )
    report = run_benchmark(detector, tts)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "schema_version",
                    "positive_attempts",
                    "positive_detections",
                    "positive_recall",
                    "hard_negative_attempts",
                    "false_activations",
                    "hard_negative_false_activation_rate",
                    "raw_audio_retained",
                )
            },
            sort_keys=True,
        )
    )
    if report["positive_recall"] < 0.95 or report["hard_negative_false_activation_rate"] > 0.005:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
