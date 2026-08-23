# Phase 10 — JARVIS Voice Core Report

## Status

The owner rejected paid/subscription wake-word services, including Picovoice
Porcupine. The zero-cost local microWakeWord path is now implemented and has
produced a Windows-compatible exact-bare-`Jarvis` TFLite candidate. It passed
manifest validation and a 100-frame silent-input runtime smoke, but Phase 10
remains blocked before physical acceptance. Synthetic training metrics are
not a reliability claim; the ASUS TUF physical gate must still measure the
owner-required pronunciation, distance/noise, negative-language,
background-conversation, playback self-trigger, latency, CPU, and RAM cases.

## Scope

The branch implements the single-device ASUS TUF voice core defined by
ADR-0010:

```text
local wake word -> local VAD/STT -> authenticated VENOM Core
-> existing ModelGateway -> local TTS -> follow-up listening
-> silence timeout -> wake-word-only idle
```

Push-to-talk is only a fallback/debug/privacy control. Voice does not call
Ollama or any model provider directly, does not execute tools, and does not
add a public or LAN listener. Phase 11 room and multi-device voice remains
`NOT_STARTED`.

## Software evidence

- Base main: `2181a7054040730cd829f091998758a68ca0482f`.
- Governance correction: `af3f762c31de55322c02002c2467cdae0bb1bcd0`.
- Runtime implementation tested at: `3d483a310ce060c2116f197bab9e8bca4149762b`.
- Unit tests, Ruff, strict mypy, and governance checks pass for the current
  implementation; the full repository check remains the completion gate.
- Pinned local adapters use the product-owned microWakeWord TFLite adapter,
  faster-whisper medium, Silero VAD, sherpa-onnx Piper/VITS, sounddevice, and
  Pipecat behind product-owned contracts. openWakeWord remains a historical
  benchmark/reference path. Exact pins and licenses are in the license
  inventory; no AccessKey or paid service is required.

## Physical gate

Physical evidence is intentionally pending. The bounded runner records only
scalar counts, timings, resource values, statuses, dependency versions, and
hashes. It does not write or commit raw audio, transcripts, credentials, or
recordings. The gate must prove 20 intended wake activations with background
and playback non-wake rounds, Arabic/English/mixed turns, follow-up without a
second wake word, silence timeout, real barge-in, PTT fallback, degraded Core
and TTS behavior, no-speech suppression, no-retention cleanup, latency, RAM,
VRAM, CPU, thermal, OOM, CUDA/display stability, and Phase 9 regressions.

The former openWakeWord candidate remains historical evidence only: its exact
hash and rejected 61.11%/5% synthetic result are preserved in
`PHASE_10_JARVIS_WAKE_MODEL.json`. The current microWakeWord candidate is
`jarvis-microwakeword-synthetic-v0.1.tflite`, SHA-256
`4cfce8663c23c6e0b4292fee42573f97225325a62917c8b3930b15ee32ee648e`, trained
by the official Apache-2.0 source at commit
`4665173cd35f1cff9a61e06fc427f124766c488e`. The artifact and config remain
outside Git and are not physical acceptance evidence. The official
`hey_jarvis_v0.1` model remains development-only because its phrase is wrong
and its CC BY-NC-SA 4.0 model terms are not adopted as the production
backend. If the microWakeWord physical gate fails, the next permitted free
path is a bounded offline Vosk keyword/grammar evaluation; no continuous
heavy Whisper or paid service may be substituted.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
