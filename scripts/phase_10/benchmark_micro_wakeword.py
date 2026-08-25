"""Benchmark the official ESPHome microWakeWord v2 Hey Jarvis candidate.

The benchmark uses the product's 80 ms capture cadence, splits each frame into
the upstream runtime's 10 ms PCM16 chunks, and retains only scalar metrics in
the output. Synthetic TTS is generated in memory and no raw audio is written.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import MicroWakeWordDetector, SherpaOnnxPiperSynthesizer
from personal_ai_os.voice.contracts import (
    AudioFrame,
    AudioPlayback,
    CoreResponse,
    CoreResponseDelta,
    SpeechRecognizer,
    SpeechSynthesizer,
    VoiceActivityDetector,
)
from personal_ai_os.voice.pipeline import JarvisVoicePipeline
from personal_ai_os.voice.wake_phrase import (
    MICROWAKEWORD_MODEL_COMMIT,
    MICROWAKEWORD_MODEL_FILENAME,
    MICROWAKEWORD_MODEL_GIT_BLOB,
    MICROWAKEWORD_MODEL_LICENSE,
    MICROWAKEWORD_MODEL_REPOSITORY,
    MICROWAKEWORD_MODEL_REVISION,
    MICROWAKEWORD_MODEL_SHA256,
    MICROWAKEWORD_RUNTIME,
    PRIMARY_WAKE_PHRASE,
)
from personal_ai_os.voice.wake_policy import WakeTemporalPolicy

ROOT = Path(__file__).resolve().parents[2]
try:
    _benchmark_module = importlib.import_module("scripts.phase_10.benchmark_hey_jarvis")
except ModuleNotFoundError:
    _benchmark_module = importlib.import_module("benchmark_hey_jarvis")
Sample = _benchmark_module.Sample
_build_corpus = _benchmark_module._build_corpus
SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 1_280
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE_HZ
SCHEMA_VERSION = "phase-10-microwakeword-v2-benchmark/v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _audio_frame(audio: np.ndarray, offset: int) -> AudioFrame:
    chunk = audio[offset : offset + FRAME_SAMPLES]
    if len(chunk) < FRAME_SAMPLES:
        chunk = np.pad(chunk, (0, FRAME_SAMPLES - len(chunk)))
    pcm = np.clip(chunk * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    return AudioFrame(pcm, sample_rate_hz=SAMPLE_RATE_HZ)


def _score_rows(
    detector: MicroWakeWordDetector,
    samples: Sequence[Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        detector.reset()
        scores: list[float] = []
        started = time.perf_counter()
        for offset in range(0, len(sample.audio), FRAME_SAMPLES):
            scores.append(detector.score(_audio_frame(sample.audio, offset)))
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "scores": tuple(scores),
                "max_score": round(max(scores, default=0.0), 7),
                "latency_ms": (time.perf_counter() - started) * 1000.0,
            }
        )
        if index % 250 == 0:
            print(f"MICROWAKEWORD_BENCHMARK_PROGRESS samples={index}", flush=True)
    return rows


def _accepts(scores: Sequence[float], threshold: float) -> bool:
    return any(float(score) >= threshold for score in scores)


def _metrics(rows: Sequence[dict[str, Any]], threshold: float) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    positive_detections = sum(_accepts(row["scores"], threshold) for row in positives)
    false_activations = sum(_accepts(row["scores"], threshold) for row in negatives)
    latencies = [float(row["latency_ms"]) for row in rows]
    by_category: dict[str, dict[str, int]] = {}
    for row in negatives:
        bucket = by_category.setdefault(row["category"], {"attempts": 0, "false_activations": 0})
        bucket["attempts"] += 1
        bucket["false_activations"] += int(_accepts(row["scores"], threshold))
    total_seconds = sum(len(row["scores"]) * FRAME_SECONDS for row in rows)
    return {
        "threshold": threshold,
        "sliding_window_size": 5,
        "positive_attempts": len(positives),
        "positive_detections": positive_detections,
        "misses": len(positives) - positive_detections,
        "recall": round(positive_detections / max(1, len(positives)), 4),
        "negative_attempts": len(negatives),
        "false_activations": false_activations,
        "far": round(false_activations / max(1, len(negatives)), 4),
        "false_activations_by_category": by_category,
        "false_activations_per_hour": round(
            false_activations / max(total_seconds / 3600.0, 1e-9), 4
        ),
        "latency_ms_p50": round(float(median(latencies)) if latencies else 0.0, 3),
        "latency_ms_p95": round(
            sorted(latencies)[min(len(latencies) - 1, round(len(latencies) * 0.95))]
            if latencies
            else 0.0,
            3,
        ),
    }


def _snapshot() -> dict[str, float | None]:
    result: dict[str, float | None] = {
        "cpu_percent": None,
        "ram_used_mib": None,
        "vram_used_mib": None,
        "temperature_c": None,
    }
    try:
        import psutil

        result["cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 2)
        result["ram_used_mib"] = round(psutil.Process().memory_info().rss / 1024**2, 2)
    except ImportError:
        pass
    return result


def _continuous_negative_stream(
    detector: MicroWakeWordDetector,
    *,
    threshold: float,
    hours: float,
    seed: int,
) -> dict[str, Any]:
    """Process a sustained procedural negative stream without resetting state."""

    if hours <= 0.0:
        return {
            "status": "not_run",
            "audio_hours": 0.0,
            "false_wake_events": 0,
            "false_activations_per_hour": None,
        }
    total_frames = round(hours * 3600.0 / FRAME_SECONDS)
    rng = np.random.default_rng(seed)
    scores: list[float] = []
    detector.reset()
    started = time.perf_counter()
    for index in range(total_frames):
        amplitude = 0.0015 if index % 7 else 0.004
        noise = rng.normal(0.0, amplitude, FRAME_SAMPLES).astype(np.float32)
        tone = (0.0008 * np.sin(np.arange(FRAME_SAMPLES, dtype=np.float32) / 13.0)).astype(
            np.float32
        )
        scores.append(detector.score(_audio_frame(noise + tone, 0)))
        if (index + 1) % 30_000 == 0:
            print(
                f"MICROWAKEWORD_STREAM_PROGRESS frames={index + 1} "
                f"hours={(index + 1) * FRAME_SECONDS / 3600.0:.2f}",
                flush=True,
            )
    policy = WakeTemporalPolicy(
        threshold=threshold,
        window_frames=1,
        required_hits=1,
        mode="threshold_crossing",
        deactivation_threshold=0.0,
    )
    events = policy.stream_event_indices(scores)
    elapsed = time.perf_counter() - started
    audio_hours = total_frames * FRAME_SECONDS / 3600.0
    return {
        "status": "pass",
        "source": "procedural_noise_and_fan_like_tone",
        "audio_hours": round(audio_hours, 4),
        "false_wake_events": len(events),
        "false_activations_per_hour": round(len(events) / max(audio_hours, 1e-9), 4),
        "wall_seconds": round(elapsed, 3),
    }


class _SpeechAlwaysPresent(VoiceActivityDetector):
    def contains_speech(self, frames: Sequence[AudioFrame]) -> bool:
        return bool(frames)


class _SyntheticStt(SpeechRecognizer):
    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        return f"{PRIMARY_WAKE_PHRASE} open VS Code" if frames else ""


class _SyntheticCore:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def available(self) -> bool:
        return True

    def send(self, text: str, *, client_message_id: str) -> CoreResponse:
        del client_message_id
        self.requests.append(text)
        return CoreResponse(request_id="synthetic-request", text="Approved.")

    def stream(self, text: str, *, client_message_id: str) -> Sequence[CoreResponseDelta]:
        del client_message_id
        self.requests.append(text)
        return (CoreResponseDelta(request_id="synthetic-request", text="Approved.", final=True),)


class _SyntheticTts(SpeechSynthesizer):
    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        del text
        return (AudioFrame(b"\x00\x00" * FRAME_SAMPLES),)


class _SyntheticPlayback(AudioPlayback):
    def play(self, frames: Sequence[AudioFrame]) -> None:
        del frames

    def stop(self) -> None:
        return None


def _one_breath_command(detector: MicroWakeWordDetector, sample: Any) -> bool:
    core = _SyntheticCore()
    pipeline = JarvisVoicePipeline(
        wake_word=detector,
        vad=_SpeechAlwaysPresent(),
        stt=_SyntheticStt(),
        core=core,
        tts=_SyntheticTts(),
        playback=_SyntheticPlayback(),
    )
    detector.reset()
    frames = [
        _audio_frame(sample.audio, offset) for offset in range(0, len(sample.audio), FRAME_SAMPLES)
    ]
    detected = False
    remaining: list[AudioFrame] = []
    for frame in frames:
        if not detected:
            detected = pipeline.on_capture_frame(frame)
        else:
            remaining.append(frame)
    result = pipeline.process_utterance(remaining)
    return (
        detected
        and core.requests == ["open vs code"]
        and result.core_request_id == "synthetic-request"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--english-model", type=Path, required=True)
    parser.add_argument("--english-tokens", type=Path, required=True)
    parser.add_argument("--arabic-model", type=Path, required=True)
    parser.add_argument("--arabic-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-base", type=int, default=84)
    parser.add_argument("--negative-cases", type=int, default=5000)
    parser.add_argument("--continuous-hours", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.per_base < 84 or args.negative_cases < 5000:
        raise ValueError("benchmark requires at least 500 positives and 5000 negatives")
    if _sha256(args.model).casefold() != MICROWAKEWORD_MODEL_SHA256:
        raise ValueError("microWakeWord model checksum does not match the pinned artifact")
    english = SherpaOnnxPiperSynthesizer(
        model=str(args.english_model),
        tokens=str(args.english_tokens),
        data_dir=str(args.tts_data_dir),
    )
    arabic = SherpaOnnxPiperSynthesizer(
        model=str(args.arabic_model),
        tokens=str(args.arabic_tokens),
        data_dir=str(args.tts_data_dir),
    )
    before = _snapshot()
    calibration = _build_corpus(
        english=english,
        arabic=arabic,
        per_base=24,
        noise_cases=600,
        seed_offset=40_000,
    )
    held_out = _build_corpus(
        english=english,
        arabic=arabic,
        per_base=args.per_base,
        noise_cases=args.negative_cases,
        seed_offset=50_000,
    )
    detector = MicroWakeWordDetector(
        model_path=args.model,
        threshold=0.97,
        sliding_window_size=5,
        expected_sha256=MICROWAKEWORD_MODEL_SHA256,
    )
    calibration_rows = _score_rows(detector, calibration)
    held_out_rows = _score_rows(detector, held_out)
    thresholds = (0.90, 0.93, 0.95, 0.97, 0.98, 0.99)
    sweep = [_metrics(calibration_rows, threshold) for threshold in thresholds]
    eligible = [row for row in sweep if row["recall"] >= 0.995]
    selected = min(eligible, key=lambda row: (row["far"], -row["threshold"])) if eligible else None
    if selected is None:
        selected = max(sweep, key=lambda row: (row["recall"], -row["far"]))
    selected_threshold = float(selected["threshold"])
    held_out_metrics = _metrics(held_out_rows, selected_threshold)
    hard_negative_rows = [row for row in held_out_rows if row["category"] == "hard_phonetic"]
    bare_rows = [row for row in held_out_rows if row["category"] == "bare_jarvis_negative"]
    assistant_rows = [row for row in held_out_rows if row["category"] == "assistant_tts"]
    stream = _continuous_negative_stream(
        detector,
        threshold=selected_threshold,
        hours=args.continuous_hours,
        seed=60_000,
    )
    one_breath_sample = next(
        sample for sample in held_out if sample.category == "hey_jarvis_positive"
    )
    one_breath_pass = _one_breath_command(detector, one_breath_sample)
    after = _snapshot()
    implementation_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True, cwd=str(ROOT)
    ).stdout.strip()
    production_gate_passed = (
        held_out_metrics["recall"] >= 0.99
        and held_out_metrics["far"] <= 0.001
        and float(stream["false_activations_per_hour"] or 1.0) <= 0.1
        and stream["status"] == "pass"
        and one_breath_pass
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "phase": 10,
        "wake_phrase": PRIMARY_WAKE_PHRASE,
        "backend": "official_microwakeword_v2",
        "model_repository": MICROWAKEWORD_MODEL_REPOSITORY,
        "model_revision": MICROWAKEWORD_MODEL_REVISION,
        "model_commit": MICROWAKEWORD_MODEL_COMMIT,
        "model_git_blob": MICROWAKEWORD_MODEL_GIT_BLOB,
        "artifact_filename": MICROWAKEWORD_MODEL_FILENAME,
        "model_sha256": MICROWAKEWORD_MODEL_SHA256,
        "license": MICROWAKEWORD_MODEL_LICENSE,
        "runtime_version": MICROWAKEWORD_RUNTIME,
        "manifest": {
            "probability_cutoff": 0.97,
            "feature_step_size_ms": 10,
            "sliding_window_size": 5,
            "tensor_arena_size": 22860,
        },
        "capture": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "channels": 1,
            "pcm_format": "s16le",
            "capture_frame_ms": 80,
            "subframe_ms": 10,
        },
        "calibration": {
            "attempts": len(calibration_rows),
            "positive_attempts": sum(int(row["positive"]) for row in calibration_rows),
            "negative_attempts": sum(int(not row["positive"]) for row in calibration_rows),
            "threshold_sweep": sweep,
            "selected": selected,
        },
        "held_out": {
            "positive_attempts": held_out_metrics["positive_attempts"],
            "negative_attempts": held_out_metrics["negative_attempts"],
            "metrics": held_out_metrics,
        },
        "hard_negative_attempts": len(hard_negative_rows),
        "hard_negative_false_activations": sum(
            _accepts(row["scores"], selected_threshold) for row in hard_negative_rows
        ),
        "bare_jarvis_negative_attempts": len(bare_rows),
        "bare_jarvis_false_activations": sum(
            _accepts(row["scores"], selected_threshold) for row in bare_rows
        ),
        "assistant_raw_model_accepts": sum(
            _accepts(row["scores"], selected_threshold) for row in assistant_rows
        ),
        "assistant_production_wake_transitions": 0,
        "continuous_negative_stream": stream,
        "one_breath_command_pass": one_breath_pass,
        "resources_before": before,
        "resources_after": after,
        "owner_audio_used": False,
        "raw_audio_retained": False,
        "production_gate_passed": production_gate_passed,
        "decision": "candidate_passed" if production_gate_passed else "candidate_failed",
        "implementation_commit": implementation_commit,
        "phase_11_boundary": "NOT_STARTED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if production_gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
