"""Benchmark the bounded Silero VAD -> faster-whisper wake path in memory.

The corpus is synthesized locally from the supplied Piper voices.  PCM is
never written; only aggregate scalar results are emitted.  Each candidate is
tested with disabled and exact-phrase hotwords so the selected production
configuration is explicit rather than silently relying on decoder bias.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import psutil

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
    VoiceDependencyUnavailable,
)
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.speech_gated_wake import SpeechGatedHeyJarvisDetector
from personal_ai_os.voice.wake_cascade import WhisperWakePhraseVerifier
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE

SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 1_280
SCHEMA_VERSION = "phase-10-speech-gated-wake-benchmark/v1"


@dataclass(frozen=True, slots=True)
class Sample:
    audio: np.ndarray
    category: str
    positive: bool


def _audio_frame(audio: np.ndarray, offset: int) -> AudioFrame:
    chunk = audio[offset : offset + FRAME_SAMPLES]
    if len(chunk) < FRAME_SAMPLES:
        chunk = np.pad(chunk, (0, FRAME_SAMPLES - len(chunk)))
    pcm = np.clip(chunk * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    return AudioFrame(pcm, sample_rate_hz=SAMPLE_RATE_HZ)


def _bounded_candidate_frame(audio: np.ndarray) -> AudioFrame:
    """Create one bounded candidate frame for fast model-comparison runs."""

    bounded = audio[: round(1.8 * SAMPLE_RATE_HZ)]
    pcm = np.clip(bounded * 32767.0, -32768, 32767).astype(np.int16).tobytes()
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
) -> list[Sample]:
    bases: tuple[tuple[str, SherpaOnnxPiperSynthesizer, tuple[str, ...], bool], ...] = (
        (
            "hey_jarvis_positive",
            english,
            (
                "Hey Jarvis",
                "Hey Jarvis open VS Code",
                "Hey Jarvis check the project",
                "Hey Jarvis tell me the system status",
                "Hey Jarvis continue the work",
                "Hey Jarvis what is left",
            ),
            True,
        ),
        (
            "english_non_wake",
            english,
            ("open VS Code", "check the project", "good morning", "read the status", "continue"),
            False,
        ),
        (
            "hard_phonetic",
            english,
            ("Hey service", "Hey Travis", "Hey Jervis", "Hello Jarvis", "Hi Jarvis", "Jarvis"),
            False,
        ),
        (
            "arabic_non_wake",
            arabic,
            (
                "افتح المشروع",
                "تحقق من الاختبارات",
                "صباح الخير",
                "اخبرني بالحالة",
                "استمر في العمل",
            ),
            False,
        ),
        (
            "background_conversation",
            english,
            ("I am speaking normally", "please continue the meeting", "the project is ready"),
            False,
        ),
        (
            "assistant_playback",
            english,
            ("Your system is ready", "the project status is complete"),
            False,
        ),
    )
    samples: list[Sample] = []
    seed = 100
    for category, tts, texts, positive in bases:
        for text in texts:
            base = _synthesize(tts, text)
            for _ in range(per_base):
                samples.append(Sample(_variant(base, seed, positive=positive), category, positive))
                seed += 1
    for index in range(noise_cases):
        samples.append(Sample(_noise(seed + index), "silence_noise", False))
    return samples


def _run_candidate(
    *,
    model: str,
    device: str,
    compute_type: str,
    hotwords: str | None,
    samples: Sequence[Sample],
    cuda_runtime_path: str | None,
    single_frame: bool,
) -> dict[str, Any]:
    print(
        f"SPEECH_GATED_BENCHMARK_CANDIDATE model={Path(model).name} "
        f"device={device} hotwords={hotwords is not None}",
        flush=True,
    )
    started = time.perf_counter()
    try:
        recognizer = FasterWhisperWakePhraseRecognizer(
            model=model,
            device=device,
            compute_type=compute_type,
            beam_size=1,
            hotwords=hotwords,
            cuda_runtime_path=cuda_runtime_path,
        )
        detector = SpeechGatedHeyJarvisDetector(
            vad=SileroVoiceActivityDetector(),
            verifier=WhisperWakePhraseVerifier(recognizer, wake_word=PRIMARY_WAKE_PHRASE),
        )
    except (OSError, RuntimeError, ValueError, VoiceDependencyUnavailable) as exc:
        return {
            "status": "unavailable",
            "model": Path(model).name,
            "device": device,
            "compute_type": compute_type,
            "hotwords": hotwords,
            "reason": type(exc).__name__.casefold(),
        }

    process = psutil.Process()
    process.cpu_percent(None)
    start_rss_mib = process.memory_info().rss / (1024 * 1024)
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        detector.reset()
        trial_started = time.perf_counter()
        accepted = False
        frames = (
            (_bounded_candidate_frame(sample.audio),)
            if single_frame
            else tuple(
                _audio_frame(sample.audio, offset)
                for offset in range(0, len(sample.audio), FRAME_SAMPLES)
            )
        )
        for frame in frames:
            if detector.detected(frame):
                accepted = True
                break
        rows.append(
            {
                "category": sample.category,
                "positive": sample.positive,
                "accepted": accepted,
                "latency_ms": (time.perf_counter() - trial_started) * 1000.0,
            }
        )
        if index % 10 == 0:
            print(f"SPEECH_GATED_BENCHMARK_PROGRESS samples={index}", flush=True)

    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    false_by_category: dict[str, int] = {}
    for row in negatives:
        if row["accepted"]:
            false_by_category[row["category"]] = false_by_category.get(row["category"], 0) + 1
    latencies = [float(row["latency_ms"]) for row in rows]
    return {
        "status": "measured",
        "model": Path(model).name,
        "device": device,
        "compute_type": compute_type,
        "beam_size": 1,
        "hotwords": hotwords,
        "positive_attempts": len(positives),
        "positive_detections": sum(bool(row["accepted"]) for row in positives),
        "recall": round(
            sum(bool(row["accepted"]) for row in positives) / max(1, len(positives)), 4
        ),
        "negative_attempts": len(negatives),
        "false_activations": sum(bool(row["accepted"]) for row in negatives),
        "far": round(sum(bool(row["accepted"]) for row in negatives) / max(1, len(negatives)), 4),
        "false_activations_by_category": false_by_category,
        "latency_ms_p50": round(float(median(latencies)) if latencies else 0.0, 3),
        "latency_ms_p95": round(
            sorted(latencies)[min(len(latencies) - 1, round(len(latencies) * 0.95))]
            if latencies
            else 0.0,
            3,
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "cpu_percent": round(process.cpu_percent(None), 2),
        "ram_rss_mib_start": round(start_rss_mib, 2),
        "ram_rss_mib_end": round(process.memory_info().rss / (1024 * 1024), 2),
        "raw_audio_retained": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--cuda-model", action="append", default=[])
    parser.add_argument("--cuda-runtime-path", default=None)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--arabic-tts-model", type=Path, required=True)
    parser.add_argument("--arabic-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--per-base", type=int, default=2)
    parser.add_argument("--noise-cases", type=int, default=24)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--single-frame",
        action="store_true",
        help="benchmark one bounded candidate frame; streaming behavior is tested separately",
    )
    args = parser.parse_args()
    if args.per_base <= 0 or args.noise_cases < 0:
        raise SystemExit("corpus bounds are invalid")

    try:
        print("SPEECH_GATED_BENCHMARK_INIT english_tts", flush=True)
        english = SherpaOnnxPiperSynthesizer(
            model=str(args.english_tts_model),
            tokens=str(args.english_tts_tokens),
            data_dir=str(args.tts_data_dir),
        )
        print("SPEECH_GATED_BENCHMARK_INIT arabic_tts", flush=True)
        arabic = SherpaOnnxPiperSynthesizer(
            model=str(args.arabic_tts_model),
            tokens=str(args.arabic_tts_tokens),
            data_dir=str(args.tts_data_dir),
        )
        print("SPEECH_GATED_BENCHMARK_SYNTHESIZE", flush=True)
        samples = _build_corpus(
            english=english,
            arabic=arabic,
            per_base=args.per_base,
            noise_cases=args.noise_cases,
        )
        print(f"SPEECH_GATED_BENCHMARK_CORPUS samples={len(samples)}", flush=True)
    except (OSError, RuntimeError, ValueError, VoiceDependencyUnavailable) as exc:
        print(f"SPEECH_GATED_BENCHMARK_BLOCKED reason={type(exc).__name__.casefold()}")
        return 2

    results: list[dict[str, Any]] = []
    for model in args.model:
        results.append(
            _run_candidate(
                model=model,
                device="cpu",
                compute_type="int8",
                hotwords=None,
                samples=samples,
                cuda_runtime_path=None,
                single_frame=args.single_frame,
            )
        )
        results.append(
            _run_candidate(
                model=model,
                device="cpu",
                compute_type="int8",
                hotwords=PRIMARY_WAKE_PHRASE,
                samples=samples,
                cuda_runtime_path=None,
                single_frame=args.single_frame,
            )
        )
    for model in args.cuda_model:
        results.append(
            _run_candidate(
                model=model,
                device="cuda",
                compute_type="float16",
                hotwords=None,
                samples=samples,
                cuda_runtime_path=args.cuda_runtime_path,
                single_frame=args.single_frame,
            )
        )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "phrase": PRIMARY_WAKE_PHRASE,
        "corpus": {
            "samples": len(samples),
            "positive_attempts": sum(sample.positive for sample in samples),
            "negative_attempts": sum(not sample.positive for sample in samples),
            "synthetic_local_tts": True,
            "raw_audio_retained": False,
        },
        "bounds": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "frame_samples": FRAME_SAMPLES,
            "max_candidate_seconds": 1.8,
            "vad_window_seconds": 0.64,
            "min_speech_seconds": 0.32,
            "initial_verification_seconds": 0.32,
            "retry_interval_seconds": 0.16,
            "max_verification_attempts": 4,
            "benchmark_single_frame": args.single_frame,
        },
        "results": results,
        "raw_audio_retained": False,
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if any(item.get("status") == "pass" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
