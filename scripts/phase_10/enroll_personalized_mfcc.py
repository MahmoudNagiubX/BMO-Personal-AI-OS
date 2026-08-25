"""Enroll three or four bare-Jarvis MFCC templates without retaining audio."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import serialize_mfcc_profile
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, choices=(3, 4), default=3)
    parser.add_argument("--seconds", type=float, choices=(2.0, 2.5, 3.0), default=2.5)
    args = parser.parse_args()
    output_path = args.output.resolve()
    repository_root = Path.cwd().resolve()
    if output_path.is_relative_to(repository_root):
        raise ValueError("wake profile must be stored outside the repository")

    sound = SoundDeviceBackend(sample_rate_hz=16_000)
    print(f"Microphone: {sound.input_device_name}")
    print(f"Playback: {sound.output_device_name}")
    print("Speak only the bare wake word: Jarvis")
    recordings: list[tuple[AudioFrame, ...]] = []
    captured: tuple[AudioFrame, ...] = ()
    try:
        for index in range(args.samples):
            input(f"Press Enter for sample {index + 1}/{args.samples}; Ctrl+C aborts: ")
            print("3...")
            time.sleep(1.0)
            print("2...")
            time.sleep(1.0)
            print("1...")
            time.sleep(1.0)
            captured = sound.capture(seconds=args.seconds)
            if not captured:
                raise RuntimeError("no bounded microphone frames were captured")
            recordings.append(captured)
        profile_text, digest = serialize_mfcc_profile(tuple(recordings))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(profile_text, encoding="utf-8")
        print(f"OWNER_WAKE_ENROLLMENT_PASS templates={len(recordings)} profile_sha256={digest}")
        print("RAW_AUDIO_RETAINED=false")
        return 0
    finally:
        recordings.clear()
        captured = ()


if __name__ == "__main__":
    raise SystemExit(main())
