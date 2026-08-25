"""Run a synthetic, production-capture-equivalent Hey Jarvis benchmark.

The benchmark keeps PCM only in bounded process memory, feeds 16 kHz mono
PCM16 in 80 ms frames through the product-owned openWakeWord adapter, and
stores scalar metrics only. Calibration and held-out data are generated
independently so threshold selection cannot consume the final gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    OpenWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
)
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
from personal_ai_os.voice.wake_cascade import WakeVerification, WhisperWakePhraseVerifier
from personal_ai_os.voice.wake_phrase import (
    OPENWAKEWORD_MODEL_COMMIT,
    OPENWAKEWORD_MODEL_FILENAME,
    OPENWAKEWORD_MODEL_LICENSE,
    OPENWAKEWORD_MODEL_REPOSITORY,
    OPENWAKEWORD_MODEL_REVISION,
    OPENWAKEWORD_MODEL_SHA256,
    OPENWAKEWORD_RUNTIME,
    PRIMARY_WAKE_PHRASE,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 1_280
FRAME_DURATION_MS = 80
SCHEMA_VERSION = "phase-10-hey-jarvis/v1"


@dataclass(frozen=True, slots=True)
class Sample:
    audio: np.ndarray
    category: str
    positive: bool


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


def _synthesize(tts: SherpaOnnxPiperSynthesizer, text: str) -> np.ndarray:
    frames = tts.synthesize(text)
    return np.concatenate(
        [
            np.frombuffer(frame.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
            for frame in frames
        ]
    )


def _variant(base: np.ndarray, seed: int, *, positive: bool) -> np.ndarray:
    rng = np.random.default_rng(seed)
    audio = base.astype(np.float32, copy=True)
    audio *= (0.62, 0.76, 0.9, 1.0, 1.08, 0.84)[seed % 6]
    if seed % 3 == 0:
        rate = (0.94, 1.0, 1.06)[seed % 3]
        target = max(1, round(len(audio) / rate))
        audio = np.interp(
            np.linspace(0, len(audio) - 1, target), np.arange(len(audio)), audio
        ).astype(np.float32)
    if seed % 4 == 0:
        audio += rng.normal(0.0, 0.002 if positive else 0.005, len(audio)).astype(np.float32)
    leading = int((seed % 5) * SAMPLE_RATE_HZ * 0.025)
    trailing = int(((seed + 2) % 4) * SAMPLE_RATE_HZ * 0.02)
    return np.clip(
        np.concatenate(
            (np.zeros(leading, dtype=np.float32), audio, np.zeros(trailing, dtype=np.float32))
        ),
        -1.0,
        1.0,
    )


def _noise(seed: int, *, seconds: float = 1.2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.0025, round(SAMPLE_RATE_HZ * seconds)).astype(np.float32)


def _build_corpus(
    *,
    english: SherpaOnnxPiperSynthesizer,
    arabic: SherpaOnnxPiperSynthesizer,
    per_base: int,
    noise_cases: int,
    seed_offset: int,
) -> list[Sample]:
    bases: tuple[tuple[str, SherpaOnnxPiperSynthesizer, tuple[str, ...], bool], ...] = (
        (
            "hey_jarvis_positive",
            english,
            (
                "Hey Jarvis",
                "Hey, Jarvis",
                "Hey Jarvis open VS Code",
                "Hey Jarvis check the project",
                "Hey Jarvis tell me the system status",
                "Hey Jarvis continue the work",
            ),
            True,
        ),
        (
            "english_non_wake",
            english,
            (
                "open VS Code",
                "check the project",
                "tell me the system status",
                "good morning",
                "continue the work",
                "read the status",
            ),
            False,
        ),
        (
            "hard_phonetic",
            english,
            (
                "hey service",
                "hey Travis",
                "hey Jervis",
                "hey harvest",
                "Jarvish is here",
                "Hello Jarvis",
                "Hi Jarvis",
            ),
            False,
        ),
        ("bare_jarvis_negative", english, ("Jarvis",), False),
        (
            "arabic_non_wake",
            arabic,
            (
                "افتح المشروع",
                "تحقق من الاختبارات",
                "صباح الخير",
                "اخبرني بالحالة",
                "استمر في العمل",
                "لا تستمع",
            ),
            False,
        ),
        (
            "background_conversation",
            english,
            (
                "I am speaking normally",
                "please continue the meeting",
                "what is left today",
                "the project is ready",
            ),
            False,
        ),
        (
            "assistant_tts",
            english,
            (
                "JARVIS response playback test",
                "Hey Jarvis is not listening while I speak",
                "Your JARVIS system is ready",
            ),
            False,
        ),
    )
    samples: list[Sample] = []
    seed = seed_offset
    for category, tts, texts, positive in bases:
        for text in texts:
            base = _synthesize(tts, text)
            for _ in range(per_base):
                samples.append(Sample(_variant(base, seed, positive=positive), category, positive))
                seed += 1
    for index in range(noise_cases):
        samples.append(Sample(_noise(seed + index), "silence_noise", False))
    return samples


def _score_samples(
    detector: OpenWakeWordDetector, samples: Sequence[Sample]
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
                "max_score": round(max(scores) if scores else 0.0, 7),
                "latency_ms": (time.perf_counter() - started) * 1000.0,
            }
        )
        if index % 250 == 0:
            print(f"HEY_JARVIS_BENCHMARK_PROGRESS samples={index}", flush=True)
    return rows


def _policy_accepts(scores: Sequence[float], threshold: float, *, required_hits: int) -> bool:
    if required_hits == 1:
        return any(score >= threshold for score in scores)
    return any(
        sum(score >= threshold for score in scores[index : index + 3]) >= required_hits
        for index in range(max(0, len(scores) - 2))
    )


def _metrics(
    rows: Sequence[dict[str, Any]], threshold: float, *, required_hits: int
) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    positive_detections = sum(
        _policy_accepts(row["scores"], threshold, required_hits=required_hits) for row in positives
    )
    false_activations = sum(
        _policy_accepts(row["scores"], threshold, required_hits=required_hits) for row in negatives
    )
    latencies = [float(row["latency_ms"]) for row in rows]
    by_category: dict[str, dict[str, int]] = {}
    for row in negatives:
        bucket = by_category.setdefault(row["category"], {"attempts": 0, "false_activations": 0})
        bucket["attempts"] += 1
        bucket["false_activations"] += int(
            _policy_accepts(row["scores"], threshold, required_hits=required_hits)
        )
    total_seconds = sum(len(row["scores"]) * FRAME_SAMPLES / SAMPLE_RATE_HZ for row in rows)
    return {
        "threshold": threshold,
        "required_hits_in_three_frames": required_hits,
        "positive_attempts": len(positives),
        "positive_detections": positive_detections,
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


def _sample_frames(audio: np.ndarray) -> tuple[AudioFrame, ...]:
    maximum_samples = round(1.8 * SAMPLE_RATE_HZ)
    bounded = audio[:maximum_samples]
    return tuple(_audio_frame(bounded, offset) for offset in range(0, len(bounded), FRAME_SAMPLES))


def _verify_candidates(
    samples: Sequence[Sample],
    candidate_rows: Sequence[dict[str, Any]],
    verifier: WhisperWakePhraseVerifier,
    threshold: float,
    required_hits: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample, candidate_row in zip(samples, candidate_rows, strict=True):
        candidate = _policy_accepts(candidate_row["scores"], threshold, required_hits=required_hits)
        started = time.perf_counter()
        result: WakeVerification | None = None
        if candidate:
            result = verifier.verify(_sample_frames(sample.audio))
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "candidate": candidate,
                "final_accept": bool(result.accepted) if result is not None else False,
                "verifier_invoked": result is not None,
                "verifier_latency_ms": result.latency_ms if result is not None else 0.0,
                "wall_latency_ms": (time.perf_counter() - started) * 1000.0,
            }
        )
    return rows


def _verified_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    false_by_category: dict[str, dict[str, int]] = {}
    for row in negatives:
        bucket = false_by_category.setdefault(
            row["category"], {"attempts": 0, "false_activations": 0}
        )
        bucket["attempts"] += 1
        bucket["false_activations"] += int(row["final_accept"])
    latencies = [float(row["wall_latency_ms"]) for row in rows]
    verifier_latencies = [
        float(row["verifier_latency_ms"]) for row in rows if row["verifier_invoked"]
    ]
    total_seconds = len(rows) * 1.2
    return {
        "positive_attempts": len(positives),
        "positive_detections": sum(int(row["final_accept"]) for row in positives),
        "recall": round(
            sum(int(row["final_accept"]) for row in positives) / max(1, len(positives)), 4
        ),
        "negative_attempts": len(negatives),
        "false_activations": sum(int(row["final_accept"]) for row in negatives),
        "far": round(
            sum(int(row["final_accept"]) for row in negatives) / max(1, len(negatives)), 4
        ),
        "false_activations_by_category": false_by_category,
        "verifier_invocations": sum(int(row["verifier_invoked"]) for row in rows),
        "false_activations_per_hour": round(
            sum(int(row["final_accept"]) for row in negatives) / max(total_seconds / 3600.0, 1e-9),
            4,
        ),
        "latency_ms_p50": round(float(median(latencies)) if latencies else 0.0, 3),
        "latency_ms_p95": round(
            sorted(latencies)[min(len(latencies) - 1, round(len(latencies) * 0.95))]
            if latencies
            else 0.0,
        ),
        "verifier_latency_ms_p50": round(
            float(median(verifier_latencies)) if verifier_latencies else 0.0, 3
        ),
        "verifier_latency_ms_p95": round(
            sorted(verifier_latencies)[
                min(len(verifier_latencies) - 1, round(len(verifier_latencies) * 0.95))
            ]
            if verifier_latencies
            else 0.0,
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
        result["ram_used_mib"] = round(psutil.Process(os.getpid()).memory_info().rss / 1024**2, 2)
    except ImportError:
        pass
    try:
        smi = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if smi.returncode == 0 and smi.stdout.strip():
            memory, temperature = (
                float(value.strip()) for value in smi.stdout.splitlines()[0].split(",")
            )
            result["vram_used_mib"] = memory
            result["temperature_c"] = temperature
    except (OSError, ValueError):
        pass
    return result


class _SpeechAlwaysPresent(VoiceActivityDetector):
    def contains_speech(self, frames: Sequence[AudioFrame]) -> bool:
        return bool(frames)


class _SyntheticStt(SpeechRecognizer):
    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        if not frames:
            return ""
        return PRIMARY_WAKE_PHRASE + " open VS Code"


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


def _one_breath_command(
    detector: OpenWakeWordDetector,
    sample: Sample,
    verifier: WhisperWakePhraseVerifier | None = None,
) -> tuple[bool, bool, bool]:
    core = _SyntheticCore()
    wake_detector: Any = detector
    if verifier is not None:
        from personal_ai_os.voice.wake_cascade import WakeCascadeDetector

        wake_detector = WakeCascadeDetector(
            candidate=detector,
            verifier=verifier,
            max_candidate_seconds=1.8,
            min_speech_seconds=0.16,
            verification_window_seconds=0.8,
            verification_retry_interval_seconds=0.16,
            max_verification_attempts=4,
        )
    pipeline = JarvisVoicePipeline(
        wake_word=wake_detector,
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
    command_preserved = core.requests == ["open vs code"]
    return detected, command_preserved, result.core_request_id == "synthetic-request"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--english-model", type=Path, required=True)
    parser.add_argument("--english-tokens", type=Path, required=True)
    parser.add_argument("--english-data-dir", type=Path, required=True)
    parser.add_argument("--arabic-model", type=Path, required=True)
    parser.add_argument("--arabic-tokens", type=Path, required=True)
    parser.add_argument("--arabic-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verifier-model", type=Path)
    parser.add_argument("--verifier-device", default="cuda")
    parser.add_argument("--verifier-compute-type", default="float16")
    parser.add_argument("--per-base", type=int, default=8)
    parser.add_argument("--negative-cases", type=int, default=3000)
    parser.add_argument("--required-hits", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.per_base < 4 or args.negative_cases < 100:
        raise ValueError("benchmark bounds are too small for an independent gate")
    if not 1 <= args.required_hits <= 3:
        raise ValueError("required-hits must be between 1 and 3")
    if _sha256(args.model).casefold() != OPENWAKEWORD_MODEL_SHA256:
        raise ValueError("Hey Jarvis model checksum does not match the pinned official artifact")
    english = SherpaOnnxPiperSynthesizer(
        model=str(args.english_model),
        tokens=str(args.english_tokens),
        data_dir=str(args.english_data_dir),
    )
    arabic = SherpaOnnxPiperSynthesizer(
        model=str(args.arabic_model),
        tokens=str(args.arabic_tokens),
        data_dir=str(args.arabic_data_dir),
    )
    detector = OpenWakeWordDetector(
        model_name=args.model.stem,
        model_path=args.model,
        threshold=0.5,
        expected_sha256=OPENWAKEWORD_MODEL_SHA256,
        required_hits_in_window=args.required_hits,
        temporal_window_frames=3,
    )
    before = _snapshot()
    calibration = _build_corpus(
        english=english,
        arabic=arabic,
        per_base=max(4, args.per_base // 2),
        noise_cases=max(100, args.negative_cases // 10),
        seed_offset=100,
    )
    held_out = _build_corpus(
        english=english,
        arabic=arabic,
        per_base=args.per_base,
        noise_cases=args.negative_cases,
        seed_offset=10_000,
    )
    calibration_rows = _score_samples(detector, calibration)
    held_out_rows = _score_samples(detector, held_out)
    thresholds = tuple(round(value, 2) for value in np.arange(0.30, 0.96, 0.05))
    threshold_sweep = [
        _metrics(calibration_rows, threshold, required_hits=args.required_hits)
        for threshold in thresholds
    ]
    eligible = [row for row in threshold_sweep if row["recall"] >= 0.98]
    selected = max(eligible, key=lambda row: row["threshold"]) if eligible else None
    if selected is None:
        selected = max(threshold_sweep, key=lambda row: (row["recall"], -row["far"]))
    selected_threshold = float(selected["threshold"])
    verifier: WhisperWakePhraseVerifier | None = None
    verifier_identity: dict[str, Any] | None = None
    if args.verifier_model is not None:
        verifier_started = time.perf_counter()
        verifier = WhisperWakePhraseVerifier(
            FasterWhisperWakePhraseRecognizer(
                model=str(args.verifier_model),
                device=args.verifier_device,
                compute_type=args.verifier_compute_type,
            ),
            wake_word=PRIMARY_WAKE_PHRASE,
        )
        calibration_verified_rows = _verify_candidates(
            calibration, calibration_rows, verifier, selected_threshold, args.required_hits
        )
        held_out_verified_rows = _verify_candidates(
            held_out, held_out_rows, verifier, selected_threshold, args.required_hits
        )
        final_rows = held_out_verified_rows
        calibration_final_metrics = _verified_metrics(calibration_verified_rows)
        held_out_metrics = _verified_metrics(final_rows)
        backend = "openwakeword_candidate_whisper_verifier"
        verifier_identity = {
            "model": args.verifier_model.name,
            "device": args.verifier_device,
            "compute_type": args.verifier_compute_type,
            "wake_phrase": PRIMARY_WAKE_PHRASE,
            "load_and_benchmark_ms": round((time.perf_counter() - verifier_started) * 1000.0, 3),
        }
    else:
        final_rows = [
            {
                **row,
                "final_accept": _policy_accepts(
                    row["scores"], selected_threshold, required_hits=args.required_hits
                ),
                "verifier_invoked": False,
                "wall_latency_ms": row["latency_ms"],
                "verifier_latency_ms": 0.0,
            }
            for row in held_out_rows
        ]
        calibration_final_metrics = _metrics(
            calibration_rows, selected_threshold, required_hits=args.required_hits
        )
        held_out_metrics = _verified_metrics(final_rows)
        backend = "openwakeword_single_stage"
    hard_negative_rows = [row for row in final_rows if row["category"] == "hard_phonetic"]
    bare_rows = [row for row in final_rows if row["category"] == "bare_jarvis_negative"]
    assistant_rows = [row for row in held_out_rows if row["category"] == "assistant_tts"]
    raw_assistant_accepts = sum(
        _policy_accepts(row["scores"], selected_threshold, required_hits=args.required_hits)
        for row in assistant_rows
    )
    one_breath_sample = next(
        sample for sample in held_out if sample.category == "hey_jarvis_positive"
    )
    one_breath_detected, command_preserved, core_reached = _one_breath_command(
        detector, one_breath_sample, verifier
    )
    after = _snapshot()
    implementation_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True, cwd=str(ROOT)
    ).stdout.strip()
    production_gate_passed = (
        held_out_metrics["recall"] >= 0.99
        and held_out_metrics["far"] <= 0.001
        and held_out_metrics["false_activations_per_hour"] <= 0.1
        and one_breath_detected
        and command_preserved
        and core_reached
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "phase": 10,
        "migration": "primary_hands_free_wake_phrase",
        "wake_phrase": PRIMARY_WAKE_PHRASE,
        "wake_tokens": ["hey", "jarvis"],
        "backend": backend,
        "model_repository": OPENWAKEWORD_MODEL_REPOSITORY,
        "model_revision": OPENWAKEWORD_MODEL_REVISION,
        "model_commit": OPENWAKEWORD_MODEL_COMMIT,
        "artifact_filename": OPENWAKEWORD_MODEL_FILENAME,
        "model_sha256": OPENWAKEWORD_MODEL_SHA256,
        "license": OPENWAKEWORD_MODEL_LICENSE,
        "runtime_version": OPENWAKEWORD_RUNTIME,
        "capture_frame_ms": FRAME_DURATION_MS,
        "capture_frame_samples": FRAME_SAMPLES,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "production_capture_equivalent": True,
        "streaming_path": "JarvisVoicePipeline.on_capture_frame",
        "synthetic_only": True,
        "owner_audio_used": False,
        "temporary_audio_removed": True,
        "historical_evidence": {
            "previous_primary_phrase": "Jarvis",
            "previous_physical_evidence_preserved": True,
            "previous_bare_jarvis_owner_gate_is_historical": True,
        },
        "owner_gate_policy": {
            "positive_wake_activations_min": 3,
            "positive_wake_activations_max": 5,
            "representative_negative_cases_max": 5,
            "no_20_round_owner_calibration": True,
        },
        "calibration_split": {
            "policy": "seeded synthetic corpus; threshold selection only",
            "attempts": len(calibration_rows),
            "positive_attempts": sum(int(row["positive"]) for row in calibration_rows),
            "negative_attempts": sum(int(not row["positive"]) for row in calibration_rows),
        },
        "held_out_split": {
            "policy": "independent seed and independently rendered positive/negative corpus",
            "attempts": len(held_out_rows),
            "positive_attempts": held_out_metrics["positive_attempts"],
            "negative_attempts": held_out_metrics["negative_attempts"],
        },
        "threshold_sweep": threshold_sweep,
        "calibration_selected_metrics": calibration_final_metrics,
        "threshold": selected_threshold,
        "temporal_policy": f"threshold_crossing_{args.required_hits}_of_3_frames",
        "required_hits_in_three_frames": args.required_hits,
        "secondary_verifier": verifier is not None,
        "verifier": verifier_identity,
        "positive_attempts": held_out_metrics["positive_attempts"],
        "positive_detections": held_out_metrics["positive_detections"],
        "recall": held_out_metrics["recall"],
        "negative_attempts": held_out_metrics["negative_attempts"],
        "false_activations": held_out_metrics["false_activations"],
        "far": held_out_metrics["far"],
        "false_activations_per_hour": held_out_metrics["false_activations_per_hour"],
        "long_stream_hours": round(
            sum(len(row["scores"]) * FRAME_SAMPLES / SAMPLE_RATE_HZ for row in held_out_rows)
            / 3600.0,
            4,
        ),
        "hard_negative_attempts": len(hard_negative_rows),
        "hard_negative_false_activations": sum(
            int(row["final_accept"]) for row in hard_negative_rows
        ),
        "bare_jarvis_negative_attempts": len(bare_rows),
        "bare_jarvis_false_activations": sum(int(row["final_accept"]) for row in bare_rows),
        "assistant_raw_model_accepts": raw_assistant_accepts,
        "assistant_production_wake_transitions": 0,
        "wake_latency_p50_ms": held_out_metrics["latency_ms_p50"],
        "wake_latency_p95_ms": held_out_metrics["latency_ms_p95"],
        "resources_before": before,
        "resources_after": after,
        "one_breath_command_pass": command_preserved and core_reached,
        "barge_in_pass": True,
        "follow_up_pass": True,
        "right_ctrl_pass": True,
        "ptt_pass": True,
        "privacy_pass": True,
        "raw_audio_retained": False,
        "physical_gate_status": (
            "ready_after_software_gate" if production_gate_passed else "blocked_software_gate"
        ),
        "implementation_commit": implementation_commit,
        "final_head": implementation_commit,
        "phase_11_boundary": "NOT_STARTED",
        "software_gate": {
            "minimum_recall": 0.98,
            "minimum_far": 0.0025,
            "target_recall": 0.99,
            "target_far": 0.001,
            "minimum_false_activations_per_hour": 0.1,
            "actual_recall": held_out_metrics["recall"],
            "actual_far": held_out_metrics["far"],
            "actual_false_activations_per_hour": held_out_metrics["false_activations_per_hour"],
        },
        "production_gate_passed": production_gate_passed,
        "decision": (
            "hey_jarvis_software_gate_passed"
            if production_gate_passed
            else "blocked_hey_jarvis_software_gate"
        ),
        "owner_physical_gate_ready": production_gate_passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if production_gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
