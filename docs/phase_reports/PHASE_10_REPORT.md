# Phase 10 — JARVIS Voice Core Report

## Status

The owner rejected paid/subscription wake-word services, including Picovoice
Porcupine. Controlled diagnostics proved the microWakeWord tensors and output
were genuine, but positive/noise separation was only approximately `0.000158`.
That candidate is confirmed defective and preserved as historical evidence.
ADR-0011 locks the next zero-cost path to offline Vosk with the exact bare
`Jarvis` grammar. The owner physical gate remains pending.

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
- The v2 software implementation at commit `94a5b980644f4d703348d78c6e6b775d845f4fe0` adds the product-owned Vosk adapter, shared
  exact-Jarvis/Right-Ctrl/PTT activation, in-memory pre-roll, Silero VAD plus
  local Pipecat Smart Turn v3.x, authenticated Core response-event reuse,
  ordered cancellable phrase TTS, and barge-in cancellation.
- The synthetic Vosk benchmark passed: 8 positive attempts, 7 detections
  (0.875 recall), 6 negative attempts, 0 false activations, and approximately
  147.4 ms median detector processing. The official small English model is
  owner-local and outside Git; only its archive and directory digests are
  recorded in sanitized v2 evidence.
- Unit tests, Ruff, strict mypy, governance, and the full repository check are
  the completion gates for the software branch. Exact pins and licenses are
  in the license inventory; no AccessKey or paid service is required.

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
`PHASE_10_JARVIS_WAKE_MODEL.json`. The rejected microWakeWord candidate is
`jarvis-microwakeword-synthetic-v0.1.tflite`, SHA-256
`4cfce8663c23c6e0b4292fee42573f97225325a62917c8b3930b15ee32ee648e`, trained
by the official Apache-2.0 source at commit
`4665173cd35f1cff9a61e06fc427f124766c488e`. The artifact and config remain
outside Git and are not physical acceptance evidence. The official
`hey_jarvis_v0.1` model remains development-only because its phrase is wrong
and its CC BY-NC-SA 4.0 model terms are not adopted as the production
backend. The v2 Vosk benchmark is the required software proof before a short
natural-use owner session; no continuous heavy Whisper or paid service may be
substituted.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
