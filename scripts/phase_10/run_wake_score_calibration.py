"""Run the bounded owner-local bare-Jarvis score calibration."""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import re
import time
from pathlib import Path
from statistics import median
from typing import Any

from personal_ai_os.voice.adapters import MicroWakeWordDetector
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend

THRESHOLDS = tuple(round(value / 10, 2) for value in range(1, 10))
SCHEMA_VERSION = "phase-10-wake-score-calibration/v1"


def _audio_level(frames: tuple[AudioFrame, ...]) -> dict[str, float]:
    """Measure scalar signed-int16 levels and immediately discard PCM."""

    samples = array.array("h", b"".join(frame.pcm_s16le for frame in frames))
    if not samples:
        return {"rms": 0.0, "peak": 0.0}
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 / 32768.0
    return {"rms": round(rms, 6), "peak": round(peak, 6)}


def _sanitize_failure(exc: BaseException) -> str:
    """Return a useful local failure without exposing secrets or private paths."""

    raw = " ".join(str(exc).split())
    lowered = raw.casefold()
    if "channel" in lowered and "multiple" in lowered:
        category = "audio format mismatch"
        raw = "duplicate channel argument in stream construction"
    elif any(term in lowered for term in ("wake", "tflite", "micro")):
        category = "wake model failure"
    elif any(term in lowered for term in ("microphone", "capture", "input")):
        category = "microphone capture failure"
    elif any(term in lowered for term in ("playback", "output", "portaudio")):
        category = "playback device failure"
    else:
        category = type(exc).__name__
    raw = re.sub(r"(?i)(bearer|token|password|secret)\s*[:=]?\s*\S+", "<redacted>", raw)
    raw = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/|\\\\)[^\s,;]+", "<path>", raw)
    return f"{category}: {(raw[:180] or 'no detail')}"


def _countdown(prompt: str) -> None:
    print(f"\n{prompt}", flush=True)
    for remaining in (3, 2, 1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)


def _capture_prompt(
    sound: SoundDeviceBackend,
    prompt: str,
    *,
    expect_audio: bool,
) -> tuple[AudioFrame, ...]:
    """Capture a bounded in-memory sample, retrying missing expected speech."""

    for attempt in range(3):
        _countdown(prompt)
        frames = sound.capture(seconds=3.0)
        level = _audio_level(frames)
        if not expect_audio or level["peak"] >= 0.003:
            return frames
        if attempt < 2:
            print("No microphone audio detected; retrying this sample.", flush=True)
    raise RuntimeError(f"no microphone audio observed for: {prompt}")


def _sample(
    detector: MicroWakeWordDetector,
    sound: SoundDeviceBackend,
    *,
    kind: str,
    scenario: str,
    trial: int,
    expect_audio: bool,
) -> dict[str, Any]:
    frames = _capture_prompt(
        sound,
        f"Calibration {kind} [{scenario} #{trial}]",
        expect_audio=expect_audio,
    )
    level = _audio_level(frames)
    started = time.perf_counter()
    maximum = max((detector.score(frame) for frame in frames), default=0.0)
    latency_ms = (time.perf_counter() - started) * 1000
    detector.reset()
    return {
        "kind": kind,
        "scenario": scenario,
        "trial": trial,
        "max_probability": round(maximum, 6),
        "audio_rms": level["rms"],
        "audio_peak": level["peak"],
        "processing_latency_ms": round(latency_ms, 1),
    }


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": round(min(values), 6),
        "median": round(median(values), 6),
        "max": round(max(values), 6),
    }


def _sweep(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positives = [sample for sample in samples if sample["kind"] == "positive"]
    negatives = [sample for sample in samples if sample["kind"] == "negative"]
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        positive_detections = sum(
            float(sample["max_probability"]) >= threshold for sample in positives
        )
        false_activations = sum(
            float(sample["max_probability"]) >= threshold for sample in negatives
        )
        rows.append(
            {
                "threshold": threshold,
                "positive_recall": round(positive_detections / len(positives), 4)
                if positives
                else 0.0,
                "misses": len(positives) - positive_detections,
                "false_activations": false_activations,
            }
        )
    return rows


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _base_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "in_progress",
        "wake_word": "Jarvis",
        "detector": "pymicro-wakeword",
        "baseline_threshold": 0.9,
        "thresholds": list(THRESHOLDS),
        "model_sha256": hashlib.sha256(args.wake_word_model.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(args.wake_word_config.read_bytes()).hexdigest(),
        "samples": [],
        "raw_audio_retained": False,
    }


def _finalize(report: dict[str, Any]) -> None:
    samples = report["samples"]
    positives = [sample for sample in samples if sample["kind"] == "positive"]
    negatives = [sample for sample in samples if sample["kind"] == "negative"]
    positive_scores = [float(sample["max_probability"]) for sample in positives]
    negative_scores = [float(sample["max_probability"]) for sample in negatives]
    positive_min = min(positive_scores) if positive_scores else 0.0
    negative_max = max(negative_scores) if negative_scores else 1.0
    margin = positive_min - negative_max
    sweep = _sweep(samples)
    valid = [
        row for row in sweep if row["positive_recall"] == 1.0 and row["false_activations"] == 0
    ]
    candidate = None
    if margin >= 0.1 and valid:
        midpoint = (positive_min + negative_max) / 2
        candidate = min(valid, key=lambda row: abs(row["threshold"] - midpoint))["threshold"]
    separated = candidate is not None
    report["score_distribution"] = {
        "positive": _stats(positive_scores),
        "negative": _stats(negative_scores),
        "positive_min_minus_negative_max": round(margin, 6),
    }
    report["threshold_sweep"] = sweep
    report["decision"] = {
        "meaningful_separation": separated,
        "candidate_threshold": candidate,
        "next_action": "rerun fresh Stage A with fixed threshold"
        if separated
        else "reject microWakeWord candidate and evaluate offline Vosk keyword grammar",
    }
    report["status"] = "complete"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wake-word-model", type=Path, required=True)
    parser.add_argument("--wake-word-config", type=Path, required=True)
    parser.add_argument("--input-device")
    parser.add_argument("--output-device")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = _base_report(args)
    _write_report(args.output, report)
    try:
        sound = SoundDeviceBackend(
            input_device=args.input_device,
            output_device=args.output_device,
        )
        print("OWNER WAKE SCORE CALIBRATION READY", flush=True)
        print(f"Microphone: {sound.input_device_name}", flush=True)
        print(f"Speaker: {sound.output_device_name}", flush=True)
        detector = MicroWakeWordDetector(
            model_path=args.wake_word_model,
            config_path=args.wake_word_config,
            threshold=0.9,
        )
        positive_scenarios = (
            ("normal pronunciation", 4),
            ("Egyptian-accented pronunciation", 2),
            ("faster pronunciation", 1),
            ("slower pronunciation", 1),
            ("quieter pronunciation", 1),
            ("moderate distance", 1),
        )
        negative_scenarios = (
            ("English normal speech", 2, True),
            ("Arabic normal speech", 2, True),
            ("background conversation", 2, True),
            ("similar-sounding non-Jarvis words", 2, True),
            ("silence", 2, False),
        )
        for scenario, count in positive_scenarios:
            for trial in range(1, count + 1):
                report["samples"].append(
                    _sample(
                        detector,
                        sound,
                        kind="positive",
                        scenario=scenario,
                        trial=trial,
                        expect_audio=True,
                    )
                )
                _write_report(args.output, report)
        for scenario, count, expect_audio in negative_scenarios:
            for trial in range(1, count + 1):
                report["samples"].append(
                    _sample(
                        detector,
                        sound,
                        kind="negative",
                        scenario=scenario,
                        trial=trial,
                        expect_audio=expect_audio,
                    )
                )
                _write_report(args.output, report)
        _finalize(report)
        _write_report(args.output, report)
        print(json.dumps(report["score_distribution"], sort_keys=True), flush=True)
        print(json.dumps(report["decision"], sort_keys=True), flush=True)
        print(f"OWNER_WAKE_SCORE_CALIBRATION_COMPLETE output={args.output.name}", flush=True)
        return 0
    except KeyboardInterrupt:
        report["status"] = "blocked"
        report["failure"] = "owner aborted calibration"
    except Exception as exc:
        report["status"] = "blocked"
        report["failure"] = _sanitize_failure(exc)
    _write_report(args.output, report)
    print(f"OWNER_WAKE_SCORE_CALIBRATION_BLOCKED: {report['failure']}", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
