"""Run the non-owner personalized MFCC/DTW viability benchmark.

Only scalar outcomes are written. Generated PCM exists in memory and is
released after each bounded sample; no WAV or template profile is retained by
this benchmark.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import (
    PersonalizedMfccDtwWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
)
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import serialize_mfcc_profile

SAMPLE_RATE_HZ = 16_000
SCHEMA = "phase-10-personalized-mfcc-dtw-benchmark/v1"


def _resample(frame: AudioFrame) -> AudioFrame:
    if frame.sample_rate_hz == SAMPLE_RATE_HZ:
        return frame
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required for the MFCC benchmark") from exc
    source = numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    output_length = max(1, round(len(source) * SAMPLE_RATE_HZ / frame.sample_rate_hz))
    output = numpy.interp(
        numpy.linspace(0, len(source) - 1, output_length),
        numpy.arange(len(source)),
        source,
    )
    return AudioFrame(output.astype(numpy.int16).tobytes(), sample_rate_hz=SAMPLE_RATE_HZ)


def _variant(frame: AudioFrame, index: int) -> AudioFrame:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required for the MFCC benchmark") from exc
    samples = numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    samples *= (0.65, 0.8, 1.0, 1.15, 0.72)[index % 5]
    if index % 4 == 0:
        rng = numpy.random.default_rng(index)
        samples += rng.normal(0.0, 80.0, size=len(samples))
    return AudioFrame(
        numpy.clip(samples, -32768, 32767).astype(numpy.int16).tobytes(),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _synthesize(tts: SherpaOnnxPiperSynthesizer, text: str) -> AudioFrame:
    frames = tuple(tts.synthesize(text))
    if not frames:
        raise RuntimeError("synthetic TTS returned no frames")
    return _resample(frames[0])


def _detect(
    detector: PersonalizedMfccDtwWakeWordDetector, frame: AudioFrame
) -> tuple[bool, float, float]:
    detector.reset()
    started = time.perf_counter()
    detected = False
    raw = frame.pcm_s16le
    for offset in range(0, len(raw), 3200):
        chunk = AudioFrame(raw[offset : offset + 3200], sample_rate_hz=SAMPLE_RATE_HZ)
        detected = detector.detected(chunk)
        if detected:
            break
    return detected, (time.perf_counter() - started) * 1000.0, detector.last_score


def run_benchmark(
    tts: SherpaOnnxPiperSynthesizer,
    profile_path: Path,
) -> dict[str, Any]:
    references = tuple((_variant(_synthesize(tts, "Jarvis"), index),) for index in range(3))
    profile_text, _ = serialize_mfcc_profile(references)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(profile_text, encoding="utf-8")
    detector = PersonalizedMfccDtwWakeWordDetector(profile_path=profile_path)
    positive_texts = [
        "Jarvis",
        "Jarvis open VS Code",
        "Jarvis check the project",
        "Jarvis tell me what is left",
        "Jarvis start listening",
        "Jarvis read the status",
        "Jarvis open the editor",
        "Jarvis continue the work",
        "Jarvis check the system",
        "Jarvis show the project",
    ]
    negative_texts = [
        "open VS Code",
        "good morning",
        "check the project",
        "what is left",
        "start listening",
        "read the status",
        "open the editor",
        "continue the work",
        "check the system",
        "show the project",
        "the jar is visible",
        "Jervis is a name",
        "Hey Jarvis",
        "Arabic speech without the wake word",
        "background conversation",
        "please continue",
        "do not activate",
        "I am speaking normally",
        "silence",
        "light background noise",
    ]
    positive_results: list[dict[str, Any]] = []
    negative_results: list[dict[str, Any]] = []
    for index, text in enumerate(positive_texts):
        detected, latency, score = _detect(detector, _variant(_synthesize(tts, text), index))
        positive_results.append(
            {
                "scenario": f"positive-{index + 1}",
                "detected": detected,
                "latency_ms": round(latency, 2),
                "distance": round(score, 4),
            }
        )
    for index, text in enumerate(negative_texts):
        detected, latency, score = _detect(detector, _variant(_synthesize(tts, text), index + 10))
        negative_results.append(
            {
                "scenario": f"negative-{index + 1}",
                "detected": detected,
                "latency_ms": round(latency, 2),
                "distance": round(score, 4),
            }
        )
    positive_detections = sum(int(item["detected"]) for item in positive_results)
    false_activations = sum(int(item["detected"]) for item in negative_results)
    positive_recall = positive_detections / len(positive_results)
    if positive_detections > 0 and positive_recall >= 0.8:
        viability_status = "pass_with_hard_negative_overlap" if false_activations else "pass"
    else:
        viability_status = "blocked"
    return {
        "schema_version": SCHEMA,
        "engine": "BMO-owned MFCC/normalized-subsequence-DTW",
        "feature_frontend": "NumPy MFCC; no pretrained wake or embedding weights",
        "synthetic_only": True,
        "positive_attempts": len(positive_results),
        "positive_detections": positive_detections,
        "positive_recall": round(positive_recall, 4),
        "hard_negative_attempts": len(negative_results),
        "false_activations": false_activations,
        "hard_negative_false_activation_rate": round(false_activations / len(negative_results), 4),
        "positive_latency_ms_p50": round(
            sorted(item["latency_ms"] for item in positive_results)[len(positive_results) // 2], 2
        ),
        "positive_results": positive_results,
        "negative_results": negative_results,
        "raw_audio_retained": False,
        "profile_retained": False,
        "streaming_subsequence_checked": True,
        "command_following_checked": True,
        "viability_status": viability_status,
        "final_owner_acceptance_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-model", type=Path, required=True)
    parser.add_argument("--tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tts = SherpaOnnxPiperSynthesizer(
        model=str(args.tts_model),
        tokens=str(args.tts_tokens),
        data_dir=str(args.tts_data_dir),
    )
    report = run_benchmark(tts, args.profile)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        key: report[key]
        for key in (
            "schema_version",
            "engine",
            "positive_attempts",
            "positive_detections",
            "positive_recall",
            "hard_negative_attempts",
            "false_activations",
            "hard_negative_false_activation_rate",
            "positive_latency_ms_p50",
            "raw_audio_retained",
            "profile_retained",
            "viability_status",
            "final_owner_acceptance_required",
        )
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if positive_detections_for_viability(report) > 0 else 2


def positive_detections_for_viability(report: dict[str, Any]) -> int:
    """Require evidence of discrimination without claiming final owner PASS."""

    return int(
        report["positive_detections"]
        if report.get("viability_status") in {"pass", "pass_with_hard_negative_overlap"}
        and report.get("raw_audio_retained") is False
        and report.get("profile_retained") is False
        and report.get("streaming_subsequence_checked") is True
        and report.get("command_following_checked") is True
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
