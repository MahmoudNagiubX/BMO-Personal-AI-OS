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

from personal_ai_os.voice.adapters import VoiceDependencyUnavailable
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


def _capture_trial(
    sound: SoundDeviceBackend,
    detector: RhasspyHeyJarvisDetector,
    probabilities: list[float],
) -> dict[str, Any]:
    try:
        input("  Press Enter when ready (Ctrl+C aborts): ")
    except EOFError as exc:
        raise RuntimeError(
            "owner-interactive microphone session is required; EOF is not a wake miss"
        ) from exc
    for count in (3, 2, 1):
        print(f"  {count}...", flush=True)
        time.sleep(1.0)
    print("  GO — speak now", flush=True)
    frames = sound.capture(seconds=2.0)
    processing_started = time.perf_counter()
    detected = False
    for frame in frames:
        detected = detector.detected(frame) or detected
    processing_ms = (time.perf_counter() - processing_started) * 1000.0
    return {
        "peak_probability": round(max(probabilities, default=0.0), 6),
        "detected": detected,
        "processing_ms": round(processing_ms, 2),
        "frames": len(frames),
    }


def _failure_reason(error: Exception) -> str:
    if isinstance(error, VoiceDependencyUnavailable):
        return "audio_or_wake_dependency_unavailable"
    if isinstance(error, (OSError, IOError)):
        return "microphone_or_audio_device_failure"
    if isinstance(error, TimeoutError):
        return "microphone_capture_timeout"
    if isinstance(error, ValueError):
        return "audio_format_or_configuration_failure"
    return "wake_probe_runtime_failure"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-device", default=None)
    args = parser.parse_args()

    try:
        sound = SoundDeviceBackend(input_device=args.input_device)
        probabilities: list[float] = []
        detector = RhasspyHeyJarvisDetector(
            threshold=DEFAULT_THRESHOLD,
            trigger_level=DEFAULT_TRIGGER_LEVEL,
            refractory_seconds=DEFAULT_REFRACTORY_SECONDS,
            probability_observer=probabilities.append,
        )
    except (VoiceDependencyUnavailable, OSError, RuntimeError, ValueError) as exc:
        print(f"WAKE_PROBE_BLOCKED reason={_failure_reason(exc)}", flush=True)
        return 2
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
            probabilities.clear()
            detector.reset()
            print(f"\n[{index}/{len(TRIALS)}] {trial.scenario}", flush=True)
            print(f"  {trial.instruction}", flush=True)
            result = _capture_trial(sound, detector, probabilities)
            result.update({"scenario": trial.scenario, "expected_wake": trial.expected_wake})
            results.append(result)
            print(
                "  RESULT "
                f"scenario={trial.scenario!r} "
                f"peak_probability={result['peak_probability']} "
                f"detected={result['detected']} "
                f"processing_ms={result['processing_ms']}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\nOWNER_ABORTED_WAKE_PROBE", flush=True)
        return 130
    except (VoiceDependencyUnavailable, OSError, RuntimeError, ValueError) as exc:
        print(f"\nWAKE_PROBE_BLOCKED reason={_failure_reason(exc)}", flush=True)
        return 2
    finally:
        detector.close()

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
