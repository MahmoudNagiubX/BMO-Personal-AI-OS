"""Canonical Phase 10 hands-free wake phrase."""

from __future__ import annotations

PRIMARY_WAKE_PHRASE = "Hey Jarvis"
PRIMARY_WAKE_TOKENS = ("hey", "jarvis")

# Historical exports retained for old reports and migration-only scripts.  The
# active runtime uses the Rhasspy constants in ``rhasspy_wake`` instead.
OPENWAKEWORD_MODEL_FILENAME = "hey_jarvis_v0.1.onnx"
OPENWAKEWORD_MODEL_REPOSITORY = "https://github.com/dscripka/openWakeWord"
OPENWAKEWORD_MODEL_REVISION = "v0.5.1"
OPENWAKEWORD_MODEL_COMMIT = "1eec2158c5c54150ac5f4c15065adacb1003b1e7"
OPENWAKEWORD_MODEL_SHA256 = "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"
OPENWAKEWORD_MODEL_LICENSE = "CC-BY-NC-SA-4.0"
OPENWAKEWORD_RUNTIME = "openwakeword==0.6.0; onnxruntime"

__all__ = [
    "OPENWAKEWORD_MODEL_COMMIT",
    "OPENWAKEWORD_MODEL_FILENAME",
    "OPENWAKEWORD_MODEL_LICENSE",
    "OPENWAKEWORD_MODEL_REPOSITORY",
    "OPENWAKEWORD_MODEL_REVISION",
    "OPENWAKEWORD_MODEL_SHA256",
    "OPENWAKEWORD_RUNTIME",
    "PRIMARY_WAKE_PHRASE",
    "PRIMARY_WAKE_TOKENS",
]
