"""Run one compact, wake-only speech-gated Hey Jarvis microphone probe.

The probe uses the production VAD -> bounded faster-whisper path.  PCM is
held only for the bounded capture call and is never written, logged, or
included in evidence.  Transcript text is intentionally never printed.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    SileroVoiceActivityDetector,
    VoiceDependencyUnavailable,
)
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend
from personal_ai_os.voice.speech_gated_wake import SpeechGatedHeyJarvisDetector
from personal_ai_os.voice.wake_cascade import WhisperWakePhraseVerifier
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE


@dataclass(frozen=True, slots=True)
class Trial:
    scenario: str
    instruction: str
    expected_wake: bool


TRIALS = (
    Trial("natural Hey Jarvis", "Say Hey Jarvis naturally.", True),
    Trial(
        "owner-accent Hey Jarvis",
        "Say Hey Jarvis naturally in your usual accent.",
        True,
    ),
    Trial(
        "moderate-distance Hey Jarvis",
        "Move a moderate distance away and say Hey Jarvis.",
        True,
    ),
    Trial("bare Jarvis negative", "Say Jarvis without Hey.", False),
    Trial(
        "English speech negative",
        "Say a normal English sentence without the wake phrase.",
        False,
    ),
    Trial("Arabic speech negative", "Say a normal Arabic sentence without the wake phrase.", False),
    Trial("hard phonetic negative", "Say a similar-sounding non-wake phrase.", False),
    Trial(
        "background negative",
        "Allow ordinary background speech without saying Hey Jarvis.",
        False,
    ),
)


def _capture_trial(
    sound: SoundDeviceBackend,
    detector: SpeechGatedHeyJarvisDetector,
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
    print("  GO - speak now", flush=True)
    detector.reset()
    frames = sound.capture(seconds=2.0)
    accepted = False
    for frame in frames:
        accepted = detector.detected(frame) or accepted
    verification = detector.last_verification
    return {
        "accepted": accepted,
        "verifier_invocations": detector.verifier_invocations,
        "verification_latency_ms": (
            round(verification.latency_ms, 2) if verification is not None else None
        ),
        "failure_category": (
            detector.last_failure_category
            or (
                verification.failure_category if verification is not None else "no_speech_candidate"
            )
        ),
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
    parser.add_argument("--model", default="base.en")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--compute-type", choices=("int8", "float16"), default="int8")
    parser.add_argument("--beam-size", type=int, choices=(1, 3, 5), default=1)
    args = parser.parse_args()

    try:
        sound = SoundDeviceBackend(input_device=args.input_device)
        vad = SileroVoiceActivityDetector()
        recognizer = FasterWhisperWakePhraseRecognizer(
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
            hotwords=None,
        )
        detector = SpeechGatedHeyJarvisDetector(
            vad=vad,
            verifier=WhisperWakePhraseVerifier(recognizer, wake_word=PRIMARY_WAKE_PHRASE),
        )
    except (VoiceDependencyUnavailable, OSError, RuntimeError, ValueError) as exc:
        print(f"WAKE_PROBE_BLOCKED reason={_failure_reason(exc)}", flush=True)
        return 2

    print("PHYSICAL JARVIS WAKE PROBE READY", flush=True)
    print(f"Microphone: {sound.input_device_name}", flush=True)
    print(f"Sample rate: {sound.sample_rate_hz} Hz", flush=True)
    print(f"Wake backend: Silero VAD -> faster-whisper ({args.model})", flush=True)
    print("Wake phrase: Hey Jarvis (exact prefix)", flush=True)
    print(f"Device: {args.device}; compute_type: {args.compute_type}; beam_size: {args.beam_size}")
    print("Hotwords: disabled", flush=True)
    print("PCM is never written or retained after each trial.", flush=True)

    results: list[dict[str, Any]] = []
    try:
        for index, trial in enumerate(TRIALS, start=1):
            print(f"\n[{index}/{len(TRIALS)}] {trial.scenario}", flush=True)
            print(f"  {trial.instruction}", flush=True)
            result = _capture_trial(sound, detector)
            result.update({"scenario": trial.scenario, "expected_wake": trial.expected_wake})
            results.append(result)
            print(
                "  RESULT "
                f"scenario={trial.scenario!r} "
                f"expected_wake={trial.expected_wake} "
                f"accepted={result['accepted']} "
                f"verifier_invocations={result['verifier_invocations']} "
                f"verification_latency_ms={result['verification_latency_ms']} "
                f"failure_category={result['failure_category']}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\nOWNER_ABORTED_WAKE_PROBE", flush=True)
        return 130
    except (VoiceDependencyUnavailable, OSError, RuntimeError, ValueError) as exc:
        print(f"\nWAKE_PROBE_BLOCKED reason={_failure_reason(exc)}", flush=True)
        return 2
    finally:
        detector.reset()

    positive = [item for item in results if item["expected_wake"]]
    negative = [item for item in results if not item["expected_wake"]]
    print(
        "\nSUMMARY "
        f"positive_detections={sum(bool(item['accepted']) for item in positive)}/{len(positive)} "
        "negative_false_activations="
        f"{sum(bool(item['accepted']) for item in negative)}/{len(negative)} "
        "raw_audio_retained=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
