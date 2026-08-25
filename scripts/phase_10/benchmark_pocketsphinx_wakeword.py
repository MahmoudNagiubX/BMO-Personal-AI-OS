"""Run the bounded offline PocketSphinx exact-``Jarvis`` fallback benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_sherpa_wakeword import run_benchmark  # type: ignore[import-not-found]

from personal_ai_os.voice.adapters import PocketSphinxWakeWordDetector, SherpaOnnxPiperSynthesizer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-model", type=Path, required=True)
    parser.add_argument("--tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    detector = PocketSphinxWakeWordDetector()
    tts = SherpaOnnxPiperSynthesizer(
        model=str(args.tts_model),
        tokens=str(args.tts_tokens),
        data_dir=str(args.tts_data_dir),
    )
    report = run_benchmark(detector, tts)
    report["engine"] = "pocketsphinx==5.0.4 default en-us model"
    report["model_license"] = "BSD-like"
    args.output.write_text(
        __import__("json").dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        __import__("json").dumps(
            {
                key: report[key]
                for key in (
                    "schema_version",
                    "engine",
                    "positive_attempts",
                    "positive_detections",
                    "positive_recall",
                    "hard_negative_attempts",
                    "false_activations",
                    "hard_negative_false_activation_rate",
                    "raw_audio_retained",
                )
            },
            sort_keys=True,
        )
    )
    if report["positive_recall"] < 0.95 or report["hard_negative_false_activation_rate"] > 0.005:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
