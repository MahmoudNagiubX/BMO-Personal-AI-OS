# Phase 10 — JARVIS Voice Core Report

## Status

The owner rejected paid/subscription wake-word services, including Picovoice
Porcupine. Controlled diagnostics proved the microWakeWord tensors and output
were genuine, but positive/noise separation was only approximately `0.000158`.
That candidate is confirmed defective and preserved as historical evidence.
ADR-0012 locks the next zero-cost path to a BMO-owned personalized MFCC/DTW
detector with the exact bare `Jarvis` phrase. The owner physical gate remains
pending.

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
- The v2 software implementation adds the product-owned personalized MFCC/DTW
  adapter, shared
  exact-Jarvis/Right-Ctrl/PTT activation, in-memory pre-roll, Silero VAD plus
  local Pipecat Smart Turn v3.x, authenticated Core response-event reuse,
  ordered cancellable phrase TTS, and barge-in cancellation.
- The non-owner MFCC viability benchmark uses generated local Piper/Sherpa
  speech and no pretrained wake/embedding weights. It recorded 10 positive
  attempts with 10 detections, 20 hard-negative attempts with 2 similar-word
  false activations, and approximately 11 ms median detector processing after
  onset bounding. This is viability evidence only; final personalized recall
  and false-activation acceptance follows one owner enrollment session.
- Unit tests, Ruff, strict mypy, governance, and the full repository check are
  the completion gates for the software branch. Exact pins and licenses are
  in the license inventory; no AccessKey or paid service is required.

## Physical gate

Physical evidence is intentionally pending. The bounded runner records only
scalar counts, timings, resource values, statuses, dependency versions, and
hashes. It does not write or commit raw audio, transcripts, credentials, or
recordings. The active owner gate is a short natural-use session: three to five
intended bare-`Jarvis` activations, a compact representative set of English,
Arabic, background, and playback non-wake cases, and one combined experience
check. It must also prove Right-Ctrl double-tap through the shared
`ActivationRouter`, one natural utterance with the command immediately after
`Jarvis`, Smart Turn across a short thinking pause, Arabic/English/mixed turns,
follow-up without a second wake word, silence timeout, real barge-in, PTT
fallback, degraded Core and TTS behavior, no-speech suppression, no-retention
cleanup, latency, RAM, VRAM, CPU, thermal, OOM, CUDA/display stability, and
Phase 9 regressions. The former 20-round owner calibration is historical only;
development reliability comes from automated/synthetic benchmarks.
At session startup the runner samples a short ambient baseline and uses
device-relative RMS/peak clamps for presence detection. A signal above the
calibrated measurable floor is always sent to the active MFCC detector; only
capture below that floor is recorded as `NO_AUDIO`, while an inference miss is
recorded as a `WAKE_MISS`. The three core activations are the acceptance gate;
quiet and faster variants are optional robustness measurements.

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
backend. The MFCC viability benchmark is the required software proof before a
short owner enrollment session; no continuous heavy Whisper, pretrained wake
model, or paid service may be substituted. The local-wake neural embedding
path is rejected because its bundled model lacks sufficient model-specific
license/provenance.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
