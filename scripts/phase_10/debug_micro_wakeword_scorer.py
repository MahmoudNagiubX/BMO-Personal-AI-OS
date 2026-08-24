"""Debug the local microWakeWord scorer with scalar diagnostics only.

The controlled probes use in-memory silence, deterministic noise, and a local
synthetic TTS rendering of ``Jarvis``.  ``--include-microphone`` adds one
short, owner-local live speech probe.  No PCM, feature tensor, or transcript is
written to the report.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import (
    MicroWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
)
from personal_ai_os.voice.contracts import AudioFrame

TARGET_SAMPLE_RATE = 16_000
PROBE_SAMPLES = TARGET_SAMPLE_RATE * 3
SCHEMA_VERSION = "phase-10-microwakeword-scorer-debug/v1"


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required for scorer diagnostics") from exc
    return numpy


def _stats(values: Any) -> dict[str, float | None]:
    if getattr(values, "size", 0) == 0:
        return {"min": None, "max": None, "mean": None, "std": None}
    return {
        "min": round(float(values.min()), 6),
        "max": round(float(values.max()), 6),
        "mean": round(float(values.mean()), 6),
        "std": round(float(values.std()), 6),
    }


def _audio_stats(samples: Any) -> dict[str, float | None]:
    numpy = _numpy()
    values = numpy.asarray(samples, dtype=numpy.float32) / 32768.0
    if values.size == 0:
        return {"rms": None, "peak": None}
    return {
        "rms": round(float(numpy.sqrt(numpy.mean(values * values))), 6),
        "peak": round(float(numpy.max(numpy.abs(values))), 6),
    }


def _fit_probe(samples: Any) -> Any:
    numpy = _numpy()
    values = numpy.asarray(samples, dtype=numpy.float32)
    if len(values) >= PROBE_SAMPLES:
        start = (len(values) - PROBE_SAMPLES) // 2
        return values[start : start + PROBE_SAMPLES].astype(numpy.int16)
    return numpy.pad(values, (0, PROBE_SAMPLES - len(values))).astype(numpy.int16)


def _synthesize_positive(tts: SherpaOnnxPiperSynthesizer) -> Any:
    numpy = _numpy()
    frames = tuple(tts.synthesize("Jarvis"))
    if len(frames) != 1:
        raise RuntimeError("synthetic positive TTS returned an unexpected frame count")
    frame = frames[0]
    samples = numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32)
    if frame.sample_rate_hz != TARGET_SAMPLE_RATE:
        target_length = max(1, round(len(samples) * TARGET_SAMPLE_RATE / frame.sample_rate_hz))
        positions = numpy.linspace(0.0, len(samples) - 1, target_length)
        samples = numpy.asarray(
            numpy.interp(positions, numpy.arange(len(samples)), samples), dtype=numpy.float32
        )
    return _fit_probe(samples)


def _probe(
    detector: MicroWakeWordDetector,
    *,
    name: str,
    source: str,
    samples: Any,
) -> dict[str, Any]:
    numpy = _numpy()
    values = numpy.asarray(samples, dtype=numpy.int16)
    frame = AudioFrame(values.tobytes(), sample_rate_hz=TARGET_SAMPLE_RATE)
    started = time.perf_counter()
    detector.reset()
    diagnostics = detector.score_diagnostics(frame)
    elapsed_ms = (time.perf_counter() - started) * 1000
    detector.reset()
    return {
        "name": name,
        "source": source,
        "audio": _audio_stats(values),
        "processing_latency_ms": round(elapsed_ms, 1),
        "diagnostics": diagnostics,
    }


def _live_microphone_probe(sound: Any) -> Any:
    print("LIVE MICROPHONE PROBE", flush=True)
    print(
        "Speak a short natural phrase after the countdown; PCM remains in memory only.", flush=True
    )
    for remaining in (3, 2, 1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)
    frames = sound.capture(seconds=3.0)
    pcm = b"".join(frame.pcm_s16le for frame in frames)
    samples = array.array("h", pcm)
    if not samples or max(abs(value) for value in samples) == 0:
        raise RuntimeError("microphone probe returned no nonzero PCM")
    return _numpy().frombuffer(pcm, dtype=_numpy().int16).copy()


def _preprocessing_contract(config: dict[str, Any]) -> dict[str, Any]:
    micro = config["micro"]
    runtime_step_ms = 10
    configured_step_ms = int(micro["feature_step_size"])
    return {
        "sample_rate_hz": TARGET_SAMPLE_RATE,
        "pcm_format": "mono signed little-endian int16",
        "frontend": "pymicro_features.MicroFrontend (pymicro-wakeword official runtime)",
        "frame_length_ms": 10,
        "feature_step_ms": runtime_step_ms,
        "configured_feature_step_ms": configured_step_ms,
        "feature_shape": [1, 1, 40],
        "normalization": "none in product adapter; runtime frontend output is passed unchanged",
        "streaming_window_order": "10 ms frontend chunks; three features concatenated on axis 1",
        "sliding_window_size": int(micro["sliding_window_size"]),
        "quantization": "runtime input/output scale and zero-point reported per probe",
        "runtime_matches_training_step": configured_step_ms == runtime_step_ms,
        "runtime_matches_training_sample_rate": True,
    }


def _evaluate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    controls = [sample for sample in samples if sample["source"] != "microphone"]
    positive = next((sample for sample in samples if sample["name"] == "synthetic_jarvis"), None)
    controls_without_positive = [sample for sample in controls if sample is not positive]
    input_stats = [sample["diagnostics"]["input_tensor_stats"] for sample in controls]
    output_stats = [sample["diagnostics"]["model_output_stats"] for sample in controls]
    input_signatures = {
        (
            item["min"],
            item["max"],
            item["mean"],
            item["std"],
        )
        for item in input_stats
        if item["min"] is not None
    }
    positive_mean: float | None = None
    if positive is not None:
        raw_positive_mean = positive["diagnostics"]["model_output_stats"]["mean"]
        if isinstance(raw_positive_mean, (int, float)):
            positive_mean = float(raw_positive_mean)
    control_means = [
        float(sample["diagnostics"]["model_output_stats"]["mean"])
        for sample in controls_without_positive
        if isinstance(sample["diagnostics"]["model_output_stats"]["mean"], (int, float))
    ]
    deltas = (
        [abs(positive_mean - value) for value in control_means] if positive_mean is not None else []
    )
    all_output_means = [item["mean"] for item in output_stats if item["mean"] is not None]
    return {
        "controlled_input_tensor_distinct_across_samples": len(input_signatures) > 1,
        "controlled_output_score_range": {
            "min": round(min(all_output_means), 6) if all_output_means else None,
            "max": round(max(all_output_means), 6) if all_output_means else None,
        },
        "synthetic_positive_mean_minus_nearest_control": (
            round(min(deltas), 6) if deltas else None
        ),
        "synthetic_positive_measurably_separated": bool(deltas and min(deltas) >= 0.01),
        "diagnostic_interpretation": (
            "input tensors vary but synthetic positive is not separated from controls"
            if deltas and min(deltas) < 0.01
            else "controlled positive/output separation requires review"
        ),
    }


def _sanitize_failure(exc: BaseException) -> str:
    raw = " ".join(str(exc).split())
    raw = re.sub(r"(?i)(bearer|token|password|secret)\s*[:=]?\s*\S+", "<redacted>", raw)
    raw = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/|\\\\)[^\s,;]+", "<path>", raw)
    return f"{type(exc).__name__}: {(raw[:180] or 'no detail')}"


def _write(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wake-word-model", type=Path, required=True)
    parser.add_argument("--wake-word-config", type=Path, required=True)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-device")
    parser.add_argument("--output-device")
    parser.add_argument("--include-microphone", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.wake_word_config.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "in_progress",
        "wake_word": "Jarvis",
        "model_sha256": hashlib.sha256(args.wake_word_model.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(args.wake_word_config.read_bytes()).hexdigest(),
        "runtime": {
            "pymicro_wakeword": "2.4.1",
            "output_path": "TfLiteTensorCopyToBuffer -> runtime dequantization -> adapter score",
        },
        "preprocessing_contract": _preprocessing_contract(config),
        "samples": [],
        "raw_audio_retained": False,
    }
    _write(args.output, report)
    try:
        detector = MicroWakeWordDetector(
            model_path=args.wake_word_model,
            config_path=args.wake_word_config,
        )
        numpy = _numpy()
        rng = numpy.random.default_rng(20260824)
        report["samples"].append(
            _probe(
                detector, name="silence", source="controlled", samples=numpy.zeros(PROBE_SAMPLES)
            )
        )
        report["samples"].append(
            _probe(
                detector,
                name="random_noise",
                source="controlled",
                samples=rng.normal(0.0, 0.1 * 32767.0, PROBE_SAMPLES),
            )
        )
        tts = SherpaOnnxPiperSynthesizer(
            model=str(args.english_tts_model),
            tokens=str(args.english_tts_tokens),
            data_dir=str(args.tts_data_dir),
        )
        report["samples"].append(
            _probe(
                detector,
                name="synthetic_jarvis",
                source="synthetic_local_tts",
                samples=_synthesize_positive(tts),
            )
        )
        if args.include_microphone:
            from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend

            sound = SoundDeviceBackend(
                input_device=args.input_device,
                output_device=args.output_device,
            )
            print(f"Microphone: {sound.input_device_name}", flush=True)
            print(f"Speaker: {sound.output_device_name}", flush=True)
            report["samples"].append(
                _probe(
                    detector,
                    name="microphone_speech",
                    source="microphone",
                    samples=_live_microphone_probe(sound),
                )
            )
        report["evaluation"] = _evaluate(report["samples"])
        report["status"] = "complete"
        _write(args.output, report)
        print("MICROWAKEWORD_SCORER_DIAGNOSTICS_COMPLETE", flush=True)
        print(json.dumps(report["evaluation"], sort_keys=True), flush=True)
    except KeyboardInterrupt:
        report["status"] = "aborted"
        _write(args.output, report)
        print("MICROWAKEWORD_SCORER_ABORTED", flush=True)
        return 2
    except Exception as exc:
        report["status"] = "blocked"
        report["failure"] = _sanitize_failure(exc)
        _write(args.output, report)
        print(f"MICROWAKEWORD_SCORER_BLOCKED: {_sanitize_failure(exc)}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
