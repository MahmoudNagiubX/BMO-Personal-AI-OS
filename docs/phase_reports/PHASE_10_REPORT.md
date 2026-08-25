# Phase 10 — JARVIS Voice Core Report

## Status

The owner rejected paid/subscription wake-word services, including Picovoice
Porcupine. Controlled diagnostics proved the microWakeWord tensors and output
were genuine, but positive/noise separation was only approximately `0.000158`.
That candidate is confirmed defective and preserved as historical evidence.
ADR-0012 locks the next zero-cost path to a BMO-owned personalized MFCC/DTW
detector with the exact bare `Jarvis` phrase. The owner physical gate remains
paused: owner enrollment is not justified by the required software-only
comparison yet. The bounded two-stage cascade follow-up is also blocked: its
best result is 56/60 (93.33%) final recall with 0/310 false activations,
below the required at-least-95% recall operating point. No owner enrollment
or new physical session is requested from this result.

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
- Personalized MFCC/DTW implementation tested at commit
  `c46bddba7e6f3350ba1e86d6d61959855008b85e`.
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

### Wake backend comparison gate

Before consuming owner enrollment, the bounded comparison runner at commit
`a7ae0f83f9827ce6e62b10ceee8f9cf8244086e8` evaluated the current BMO
MFCC/DTW path against WakeForge's locally constructed MFCC + GRU ONNX path at
upstream revision `1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7`. Both used the
same held-out synthetic corpus: 48 positives and 248 negatives spanning
normal English, hard phonetic, Arabic, mixed, background conversation, and
silence/noise. No owner audio, Hugging Face dataset, cloud TTS, voice
conversion, or pre-exported remote feature artifact was used; generated audio
and intermediate models were temporary and removed.

- BMO: 37/48 positives (77.08% recall), 15/248 false activations (6.05%),
  all hard-phonetic; median/p95/max processing latency 141.739/1517.792/2106.129
  ms.
- WakeForge at fixed threshold 0.5: 48/48 positives (100% recall), but
  248/248 false activations (100%), including silence/noise; median/p95/max
  latency 33.801/111.056/148.495 ms. Its score ranges materially overlap.

WakeForge code and the OVOS references are Apache-2.0, but the locally used
Piper assets are evaluation-only: Lessac points to a research-only Blizzard
2013 license and the Arabic source does not expose a clear SPDX license. The
comparison therefore does not authorize distribution, runtime integration, or
owner enrollment. BMO remains the active product-owned backend, but neither
backend is enrollment-ready and no threshold is being promoted from this
corpus. Full scalar evidence is in
`evidence/PHASE_10_WAKE_BACKEND_COMPARISON.json`; ADR-0013 records the block.

### Two-stage cascade software gate

The follow-up runner at implementation commit
`b5dcd69bbd235d63f8ae0c66a2f0843428a8977c` evaluated two bounded local
cascades: BMO MFCC/DTW → MIT-licensed faster-whisper-small and WakeForge →
the same verifier. A VAD → Whisper control was also measured. All three
reached the same maximum of 56/60 (93.33%) final recall with 0/310 false
activations on the held-out synthetic corpus. The target is at least 95%
recall and at most 0.5% false activation rate, so the cascade remains blocked
and no winner or threshold is promoted. The CPU verifier's candidate-to-
verification latency was approximately 4996.597 ms p50 and 5865.029 ms p95;
the attempted CUDA run was not usable because `cublas64_12.dll` was missing.
The CPU run intentionally attributes no GPU residency or temperature to the
verifier. Full scalar evidence is in
`evidence/PHASE_10_WAKE_CASCADE.json`; ADR-0014 records this decision.

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
backend. The MFCC, backend-comparison, and cascade benchmarks are required
software proof before a short owner enrollment session; no owner audio or
physical retest is requested while the cascade is blocked. No continuous
heavy Whisper, pretrained wake model, or paid service may be substituted. The
local-wake neural embedding
path is rejected because its bundled model lacks sufficient model-specific
license/provenance.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
