"""Run an automated, synthetic-only Vosk exact-Jarvis wake benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import SherpaOnnxPiperSynthesizer, VoskWakeWordDetector
from personal_ai_os.voice.contracts import AudioFrame

SAMPLE_RATE = 16_000
PROBE_SECONDS = 2.5
SCHEMA = "phase-10-vosk-wake-benchmark/v1"


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required for the Vosk benchmark") from exc
    return numpy


def _fit(samples: Any) -> Any:
    numpy = _numpy()
    count = int(SAMPLE_RATE * PROBE_SECONDS)
    values = numpy.asarray(samples, dtype=numpy.float32)
    if len(values) >= count:
        return values[:count].astype(numpy.int16)
    return numpy.pad(values, (0, count - len(values))).astype(numpy.int16)


def _tts(tts: SherpaOnnxPiperSynthesizer, text: str) -> Any:
    numpy = _numpy()
    frames = tuple(tts.synthesize(text))
    if len(frames) != 1:
        raise RuntimeError("synthetic TTS returned an unexpected frame count")
    frame = frames[0]
    values = numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    if frame.sample_rate_hz != SAMPLE_RATE:
        target = max(1, round(len(values) * SAMPLE_RATE / frame.sample_rate_hz))
        positions = numpy.linspace(0.0, len(values) - 1, target)
        values = numpy.asarray(numpy.interp(positions, numpy.arange(len(values)), values))
    return _fit(values)


def _variant(samples: Any, *, gain: float = 1.0, speed: float = 1.0, noise: float = 0.0) -> Any:
    numpy = _numpy()
    values = numpy.asarray(samples, dtype=numpy.float32) * gain
    if speed != 1.0:
        target = max(1, round(len(values) / speed))
        positions = numpy.linspace(0.0, len(values) - 1, target)
        values = numpy.asarray(numpy.interp(positions, numpy.arange(len(values)), values))
    if noise:
        rng = numpy.random.default_rng(round(gain * 1000) + round(speed * 100))
        values = values + rng.normal(0.0, noise * 32768.0, len(values))
    return _fit(numpy.clip(values, -32768, 32767))


def _sample(detector: VoskWakeWordDetector, label: str, samples: Any) -> dict[str, Any]:
    values = _numpy().asarray(samples, dtype=_numpy().int16)
    frame = AudioFrame(values.tobytes(), sample_rate_hz=SAMPLE_RATE)
    started = time.perf_counter()
    detector.reset()
    detected = detector.detected(frame)
    elapsed = (time.perf_counter() - started) * 1000
    detector.reset()
    return {
        "label": label,
        "detected": detected,
        "processing_latency_ms": round(elapsed, 2),
        "rms": round(float((_numpy().mean((values / 32768.0) ** 2)) ** 0.5), 6),
        "peak": round(float(_numpy().max(_numpy().abs(values)) / 32768.0), 6),
    }


def _sanitize_failure(exc: BaseException) -> str:
    raw = " ".join(str(exc).split())
    raw = re.sub(r"(?i)(password|secret|token)\s*[:=]?\s*\S+", "<redacted>", raw)
    raw = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/|\\\\)[^\s,;]+", "<path>", raw)
    return f"{type(exc).__name__}: {(raw[:180] or 'no detail')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "in_progress",
        "wake_word": "Jarvis",
        "engine": "vosk==0.3.45",
        "model_sha256": hashlib.sha256(
            b"".join(path.read_bytes() for path in sorted(args.model.rglob("*")) if path.is_file())
        ).hexdigest(),
        "grammar": ["jarvis", "[unk]"],
        "synthetic_only": True,
        "raw_audio_retained": False,
        "samples": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        detector = VoskWakeWordDetector(model_path=args.model)
        tts = SherpaOnnxPiperSynthesizer(
            model=str(args.english_tts_model),
            tokens=str(args.english_tts_tokens),
            data_dir=str(args.tts_data_dir),
        )
        positive = _tts(tts, "Jarvis")
        negative_phrases = (
            ("english_negative", "good morning"),
            ("similar_negative", "Jervis"),
            ("hey_negative", "Hey Jarvis"),
            ("arabic_negative", "مرحبا كيف حالك"),
        )
        positives = (
            ("normal_1", _variant(positive)),
            ("normal_2", _variant(positive, gain=0.85)),
            ("egyptian_accent_proxy_1", _variant(positive, speed=0.92, gain=0.8)),
            ("egyptian_accent_proxy_2", _variant(positive, speed=1.08, gain=0.95)),
            ("fast", _variant(positive, speed=1.18)),
            ("slow", _variant(positive, speed=0.86)),
            ("quiet", _variant(positive, gain=0.42)),
            ("noise", _variant(positive, noise=0.01)),
        )
        for label, samples in positives:
            report["samples"].append(_sample(detector, label, samples))
        for label, phrase in negative_phrases:
            report["samples"].append(_sample(detector, label, _tts(tts, phrase)))
        numpy = _numpy()
        report["samples"].append(
            _sample(detector, "silence", numpy.zeros(int(SAMPLE_RATE * PROBE_SECONDS)))
        )
        report["samples"].append(
            _sample(
                detector,
                "random_noise",
                numpy.random.default_rng(20260824).normal(
                    0.0, 0.08 * 32767, int(SAMPLE_RATE * PROBE_SECONDS)
                ),
            )
        )
        positives_result = [
            item for item in report["samples"] if item["label"] in {label for label, _ in positives}
        ]
        negatives_result = [item for item in report["samples"] if item not in positives_result]
        detected_count = sum(bool(item["detected"]) for item in positives_result)
        false_count = sum(bool(item["detected"]) for item in negatives_result)
        report["evaluation"] = {
            "positive_attempts": len(positives_result),
            "positive_detections": detected_count,
            "positive_recall": round(detected_count / len(positives_result), 4),
            "negative_attempts": len(negatives_result),
            "false_activations": false_count,
            "separation_usable": detected_count / len(positives_result) >= 0.8 and false_count == 0,
        }
        report["status"] = "complete"
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("VOSK_WAKE_BENCHMARK_COMPLETE", flush=True)
        print(json.dumps(report["evaluation"], sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        report["status"] = "blocked"
        report["failure"] = _sanitize_failure(exc)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"VOSK_WAKE_BENCHMARK_BLOCKED: {_sanitize_failure(exc)}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
