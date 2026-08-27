"""Run a short owner-local audio preflight without wake-word trials or file output."""

from __future__ import annotations

import argparse
import array
import re
import threading
import time
from pathlib import Path

from personal_ai_os.voice.adapters import SherpaOnnxPiperSynthesizer
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend


def _audio_level(frames: tuple[AudioFrame, ...]) -> dict[str, float]:
    """Measure scalar signed-int16 levels and discard the PCM before returning."""

    samples = array.array("h", b"".join(frame.pcm_s16le for frame in frames))
    if not samples:
        return {"rms": 0.0, "peak": 0.0}
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 / 32768.0
    return {"rms": round(rms, 6), "peak": round(peak, 6)}


def _sanitize_failure(exc: BaseException) -> str:
    """Print a useful local failure category without paths, secrets, or PCM."""

    raw = " ".join(str(exc).split())
    lowered = raw.casefold()
    if "channel" in lowered and "multiple" in lowered:
        category = "audio format mismatch"
        raw = "duplicate channel argument in stream construction"
    elif any(term in lowered for term in ("tts", "sherpa", "onnx", "model")):
        category = "TTS/model failure"
    elif any(term in lowered for term in ("playback", "output", "portaudio")):
        category = "playback device failure"
    elif any(term in lowered for term in ("format", "sample rate", "channel", "pcm")):
        category = "audio format mismatch"
    elif any(term in lowered for term in ("microphone", "capture", "input")):
        category = "microphone capture failure"
    else:
        category = type(exc).__name__
    raw = re.sub(r"(?i)(bearer|token|password|secret)\s*[:=]?\s*\S+", "<redacted>", raw)
    raw = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/|\\\\)[^\s,;]+", "<path>", raw)
    return f"{category}: {(raw[:180] or 'no detail')}"


def _countdown() -> None:
    print("Speak normally toward the selected microphone after the countdown.", flush=True)
    for remaining in (2, 1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)


def _run(args: argparse.Namespace) -> None:
    sound = SoundDeviceBackend(
        input_device=args.input_device,
        output_device=args.output_device,
    )
    print("AUDIO_PREFLIGHT_READY", flush=True)
    print(f"Microphone: {sound.input_device_name}", flush=True)
    print(f"Speaker: {sound.output_device_name}", flush=True)

    _countdown()
    microphone_frames = sound.capture(seconds=1.0)
    microphone_level = _audio_level(microphone_frames)
    if microphone_level["peak"] <= 0.0001:
        raise RuntimeError("microphone capture returned no nonzero PCM")
    print(
        "MICROPHONE_CAPTURE_PASS "
        f"frames={len(microphone_frames)} rms={microphone_level['rms']:.6f} "
        f"peak={microphone_level['peak']:.6f}",
        flush=True,
    )

    tts = SherpaOnnxPiperSynthesizer(
        model=str(args.english_tts_model),
        tokens=str(args.english_tts_tokens),
        data_dir=str(args.tts_data_dir),
    )
    sample = tuple(tts.synthesize("Audio preflight complete."))
    if not sample:
        raise RuntimeError("English TTS produced no audio frames")
    print(f"TTS_SYNTHESIS_PASS frames={len(sample)}", flush=True)

    sound.play(sample)
    print("PLAYBACK_STREAM_PASS", flush=True)

    playback_error: list[Exception] = []

    def play_sample() -> None:
        try:
            sound.play(sample)
        except Exception as exc:
            playback_error.append(exc)

    playback_thread = threading.Thread(target=play_sample, daemon=True)
    playback_thread.start()
    try:
        simultaneous_frames = sound.capture(seconds=1.0)
    finally:
        playback_thread.join(timeout=15)
    if playback_thread.is_alive():
        sound.stop()
        playback_thread.join(timeout=2)
        raise TimeoutError("simultaneous playback/capture did not terminate within 15 seconds")
    if playback_error:
        raise playback_error[0]
    simultaneous_level = _audio_level(simultaneous_frames)
    if not simultaneous_frames:
        raise RuntimeError("simultaneous capture returned no frames")
    print(
        "SIMULTANEOUS_CAPTURE_PLAYBACK_PASS "
        f"frames={len(simultaneous_frames)} rms={simultaneous_level['rms']:.6f} "
        f"peak={simultaneous_level['peak']:.6f}",
        flush=True,
    )
    print("RAW_AUDIO_RETAINED=false", flush=True)
    print("OWNER_AUDIO_PREFLIGHT_PASS", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--input-device")
    parser.add_argument("--output-device")
    args = parser.parse_args()
    try:
        _run(args)
    except KeyboardInterrupt:
        print("OWNER_AUDIO_PREFLIGHT_BLOCKED: owner aborted", flush=True)
        return 2
    except Exception as exc:
        print(f"OWNER_AUDIO_PREFLIGHT_BLOCKED: {_sanitize_failure(exc)}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
