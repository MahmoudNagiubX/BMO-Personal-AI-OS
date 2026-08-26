"""Run one compact, wake-only Rhasspy Hey Jarvis microphone probe.

This diagnostic intentionally has no STT, TTS, Core, or file/audio output.
PCM is held only for the bounded capture call and immediately consumed by the
streaming detector.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

from personal_ai_os.voice.rhasspy_wake import (
    DEFAULT_REFRACTORY_SECONDS,
    DEFAULT_THRESHOLD,
    DEFAULT_TRIGGER_LEVEL,
    HEY_JARVIS_MODEL_FILENAME,
    PYOPEN_WAKEWORD_VERSION,
    RhasspyHeyJarvisDetector,
)
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend


@dataclass(frozen=True, slots=True)
class Trial:
    scenario: str
    instruction: str
    expected_wake: bool


TRIALS = (
    Trial("normal Hey Jarvis", "Say Hey Jarvis naturally.", True),
    Trial("Egyptian-accented Hey Jarvis", "Say Hey Jarvis naturally in your usual accent.", True),
    Trial(
        "moderate-distance Hey Jarvis", "Move a moderate distance away and say Hey Jarvis.", True
    ),
    Trial("bare Jarvis negative", "Say Jarvis without Hey.", False),
    Trial(
        "English speech negative", "Say a normal English sentence without the wake phrase.", False
    ),
    Trial("Arabic speech negative", "Say a normal Arabic sentence without the wake phrase.", False),
    Trial("hard phonetic negative", "Say a similar-sounding non-wake phrase.", False),
    Trial(
        "background negative", "Allow ordinary background speech without saying Hey Jarvis.", False
    ),
)


def _capture_trial(sound: SoundDeviceBackend, detector: RhasspyHeyJarvisDetector) -> dict[str, Any]:
    try:
        input("  Press Enter, then speak during the two-second capture window (Ctrl+C aborts): ")
    except EOFError as exc:
        raise RuntimeError(
            "owner-interactive microphone session is required; EOF is not a wake miss"
        ) from exc
    print("  Capturing...", flush=True)
    started = time.perf_counter()
    frames = sound.capture(seconds=2.0)
    detected = False
    for frame in frames:
        detected = detector.detected(frame) or detected
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "peak_probability": round(detector.last_probability, 6),
        "detected": detected,
        "latency_ms": round(elapsed_ms, 2),
        "frames": len(frames),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-device", default=None)
    args = parser.parse_args()

    sound = SoundDeviceBackend(input_device=args.input_device)
    detector = RhasspyHeyJarvisDetector(
        threshold=DEFAULT_THRESHOLD,
        trigger_level=DEFAULT_TRIGGER_LEVEL,
        refractory_seconds=DEFAULT_REFRACTORY_SECONDS,
    )
    print("PHYSICAL JARVIS WAKE PROBE READY", flush=True)
    print(f"Microphone: {sound.input_device_name}", flush=True)
    print(f"Sample rate: {sound.sample_rate_hz} Hz", flush=True)
    print("Chunk cadence: 10 ms / 160 samples / 320 bytes", flush=True)
    print(f"Model: {HEY_JARVIS_MODEL_FILENAME}", flush=True)
    print(f"Runtime: pyopen-wakeword=={PYOPEN_WAKEWORD_VERSION}", flush=True)
    print(f"Threshold: {detector.threshold}", flush=True)
    print(f"Trigger level: {detector.trigger_level}", flush=True)
    print(f"Refractory: {detector.refractory_seconds}s", flush=True)
    print("PCM is never written or retained after each trial.", flush=True)

    results: list[dict[str, Any]] = []
    try:
        for index, trial in enumerate(TRIALS, start=1):
            detector.reset()
            print(f"\n[{index}/{len(TRIALS)}] {trial.scenario}", flush=True)
            print(f"  {trial.instruction}", flush=True)
            print("  3... 2... 1...", flush=True)
            result = _capture_trial(sound, detector)
            result.update({"scenario": trial.scenario, "expected_wake": trial.expected_wake})
            results.append(result)
            print(
                "  RESULT "
                f"scenario={trial.scenario!r} "
                f"peak_probability={result['peak_probability']} "
                f"detected={result['detected']} "
                f"latency_ms={result['latency_ms']}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\nOWNER_ABORTED_WAKE_PROBE", flush=True)
        return 130

    positive = [item for item in results if item["expected_wake"]]
    negative = [item for item in results if not item["expected_wake"]]
    print(
        "\nSUMMARY "
        f"positive_detections={sum(bool(item['detected']) for item in positive)}/{len(positive)} "
        "negative_false_activations="
        f"{sum(bool(item['detected']) for item in negative)}/{len(negative)} "
        "raw_audio_retained=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
