# Phase 10 — JARVIS Voice Core Report

## Status

The first custom local bare-`Jarvis` candidate is software-tested, but Phase
10 is blocked before physical acceptance. The candidate's held-out synthetic
benchmark is only 61.11% recall at a 0.9 threshold with 5% false activation,
so it is not reliable enough to take to the owner physical gate as a
production wake backend. This report does not claim physical acceptance or a
Phase 10 PASS.

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
- Runtime implementation tested at: `e65f167acd725176c963aa76d5d0f5cd4656550d`.
- Unit tests, Ruff, strict mypy, and governance checks pass for the current
  implementation; the full repository check remains the completion gate.
- Pinned local adapters use faster-whisper medium, Silero VAD, openWakeWord
  ONNX, sherpa-onnx Piper/VITS, sounddevice, and Pipecat behind product-owned
  contracts. Exact pins and license notes are in the license inventory.

## Physical gate

Physical evidence is intentionally pending. The bounded runner records only
scalar counts, timings, resource values, statuses, dependency versions, and
hashes. It does not write or commit raw audio, transcripts, credentials, or
recordings. The gate must prove 20 intended wake activations with background
and playback non-wake rounds, Arabic/English/mixed turns, follow-up without a
second wake word, silence timeout, real barge-in, PTT fallback, degraded Core
and TTS behavior, no-speech suppression, no-retention cleanup, latency, RAM,
VRAM, CPU, thermal, OOM, CUDA/display stability, and Phase 9 regressions.

The attempted candidate is `jarvis-openwakeword-synthetic-v0.1.onnx`, trained
from synthetic local TTS only and kept outside Git. Its exact hash and
metrics are in `PHASE_10_JARVIS_WAKE_MODEL.json`. The former official
`hey_jarvis_v0.1` model remains development-only because its phrase is wrong
and its CC BY-NC-SA 4.0 model terms are not adopted as the production
backend. The next backend decision is therefore owner-controlled: approve a
better local openWakeWord training path, or evaluate an approved alternative.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
