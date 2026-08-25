# Phase 10 — JARVIS Voice Core Report

## Status

The owner rejected paid/subscription wake-word services, including Picovoice
Porcupine. Controlled diagnostics proved the microWakeWord tensors and output
were genuine, but positive/noise separation was only approximately `0.000158`.
That candidate is confirmed defective and preserved as historical evidence.
The owner then authorized migration of the primary hands-free phrase to the
exact `Hey Jarvis` phrase. ADR-0018 records the official openWakeWord artifact,
its provenance/checksum, and the bounded candidate/verifier software gate. The
previous bare-`Jarvis` physical evidence remains historical only.
The bounded two-stage cascade follow-up remains historical and blocked: its
best result is 56/60 (93.33%) final recall with 0/310 false activations,
below the required at-least-95% recall operating point. No owner enrollment or
physical session was requested from that result.

The final verifier optimization pass at implementation commit
`e9de3ead8b1deccf67e135ab0f84e02ee805ce30` also remains blocked. The approved
CUDA runtime loaded successfully, and the pinned tiny.en, base.en, and
small.en models were tested with the dedicated English short-phrase decode
contract. On the final independent held-out corpus (150 positives and 1,075
negatives), the best base.en result was 144/150 (96.0% recall) with 45/1,075
(4.19%) false activations. All false activations were assistant/JARVIS
playback samples. This is above the 0.5% FAR limit, so no verifier is
selected and no physical owner session is requested. ADR-0015 records the
decision; scalar evidence is in
`evidence/PHASE_10_WAKE_VERIFIER_OPTIMIZATION.json`.

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

## Final wake architecture audit

The final active architecture is exactly one local cascade: official
openWakeWord `hey_jarvis_v0.1.onnx` candidate followed by a bounded
faster-whisper `base.en` exact-prefix verifier. Candidate threshold/VAD and
temporal policy are calibration-selected; production evidence also requires
a continuous scalar stream of at least five hours with no more than 0.1 false
activations/hour. The owner gate is compact: three to five intended
activations plus representative negatives, one natural pre-roll command,
Right-Ctrl double-tap through the shared router, Smart Turn, follow-up,
barge-in, sleep, PTT, privacy, resource, and Phase 9/Qwen regressions. The
former 20-round owner calibration is historical only.

The authoritative held-out run at
`e103a62523dcfa1253c449775492e34a4497359d` measured 110/120 recall (91.67%),
24/3,540 false activations (0.68%), and 19.6721 false activations/hour.
Continuous-stream evidence was not run because the required local TTS/corpus
artifacts are absent in this workspace. The software gate therefore remains
blocked and no owner physical session is authorized. Sanitized details are
in `evidence/PHASE_10_HEY_JARVIS_FINAL.json`; provenance is in
`evidence/PHASE_10_HEY_JARVIS_MODEL.json`; ADR-0019 records the cleanup.

## Historical superseded software evidence

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
The earlier CUDA attempt was not usable because `cublas64_12.dll` was missing;
the later optimization pass resolved and verified the complete local runtime.
Full scalar evidence for the earlier run is in
`evidence/PHASE_10_WAKE_CASCADE.json`; ADR-0014 records this decision.

### English verifier optimization gate

The dedicated verifier uses pinned MIT-licensed Systran faster-whisper
`tiny.en`, `base.en`, and `small.en` artifacts, with no forced prefix and
bounded English decoding. The CUDA load gate passed using the approved local
CUDA 12 runtime/BLAS bundle plus pinned CTranslate2 cuDNN 9. A configuration
sweep covered BMO MFCC/DTW, WakeForge, and Silero VAD candidate stages,
leading/onset conditioning, beams 1/3/5, and the optional exact `Jarvis`
hotword. The isolated acoustic evaluation showed 144/150 positive detections
(96.0% recall) and 0/975 external negative false activations (0.0% FAR), with
45 false activations occurring exclusively on synthetic assistant TTS playback.
See `evidence/PHASE_10_WAKE_VERIFIER_OPTIMIZATION.json` and ADR-0015.

### State-aware wake arming and self-playback isolation

The 45 assistant playback detections identified in ADR-0015 were addressed by
hardening `JarvisVoicePipeline` and its state machine:
1. Wake inference is armed strictly when `self.state is VoiceState.SLEEPING`.
   During `SPEAKING`, `FOLLOW_UP_LISTENING`, `LISTENING`, `TRANSCRIBING`, and
   `SENDING`, capture frames return `False` immediately with zero verifier
   invocations.
2. Pre-roll accumulation occurs strictly during `VoiceState.SLEEPING`.
   Assistant TTS playback audio cannot enter pre-roll buffers or contaminate
   subsequent turns.
3. Explicit detector resets and rolling buffer cleanups are executed across
   `sleep()`, silence timeouts, barge-in, manual capture, and turn completions.
4. Linux CI portability in CUDA runtime loading was restored via platform-safe
   `_register_dll_directory`.

The pre-fix stateful artifact is preserved as historical evidence only: it used
whole-utterance frames and did not reproduce the physical 80 ms capture cadence.
The owner's first real `vad_whisper` Stage-A result was 0/3 intended detections
with zero false activations; it is retained as a pre-fix physical result, not a
pronunciation failure. The corrected benchmark now splits every synthetic
sample into 80 ms, 16 kHz mono PCM16 frames and feeds the same
`JarvisVoicePipeline.on_capture_frame` path as production. Its bounded timing
sweep selected a 320 ms initial window with 160 ms retries and four maximum
verifier calls. The full held-out run recorded 149/150 (99.33%) sleeping recall
and 0/975 external false activations, with zero verifier calls/transitions during
100 speaking and 100 follow-up assistant-playback samples, 20/20 barge-in, and
19/20 single-utterance pre-roll preservation. The realistic streaming software
gate passes and one compact owner physical retest is now permitted. See
`evidence/PHASE_10_STREAMING_WAKE_PATH.json` and ADR-0017.

## Physical gate

The Hey Jarvis migration software gate is the current acceptance boundary. The
full independent held-out run used 120 positives and 3,540 negatives with the
pinned candidate-plus-verifier profile. It recorded 110/120 recall (91.67%),
24/3,540 false activations (0.68%), and 19.67 false activations/hour, so the
software gate is blocked and does not authorize owner audio. Physical evidence
is intentionally pending. The bounded runner records only
scalar counts, timings, resource values, statuses, dependency versions, and
hashes. It does not write or commit raw audio, transcripts, credentials, or
recordings. Once the software gate passes, the active owner gate is a short
natural-use session: three to five intended `Hey Jarvis` activations, a compact
representative set of English,
Arabic, background, and playback non-wake cases, and one combined experience
check. It must also prove Right-Ctrl double-tap through the shared
`ActivationRouter`, one natural utterance with the command immediately after
the wake phrase, Smart Turn across a short thinking pause, Arabic/English/mixed
turns, follow-up without a second wake word, silence timeout, real barge-in, PTT
fallback, degraded Core and TTS behavior, no-speech suppression, no-retention
cleanup, latency, RAM, VRAM, CPU, thermal, OOM, CUDA/display stability, and
Phase 9 regressions. The former 20-round owner calibration is historical only;
development reliability comes from automated/synthetic benchmarks. No owner
session is authorized while the migration software gate is blocked.
At session startup the runner samples a short ambient baseline and uses
device-relative RMS/peak clamps for presence detection. A signal above the
calibrated measurable floor is always sent to the active wake cascade detector; only
capture below that floor is recorded as `NO_AUDIO`, while an inference miss is
recorded as a `WAKE_MISS`. The three core activations are the acceptance gate;
quiet and faster variants are optional robustness measurements.
The loopback launcher (`run_local_acceptance.ps1`) manages the SSH tunnel to VENOM
Core with a bounded 20-second readiness deadline exceeding ConnectTimeout, preflights
local port 18000 to reuse valid existing tunnels or reject conflicting listeners,
verifies unauthenticated `/health/live` reachability before invoking physical acceptance,
and surfaces categorized sanitized diagnostics (`SSH_AUTH_FAILED`, `SSH_HOST_KEY_FAILED`,
`SSH_HOST_UNREACHABLE`, `LOCAL_PORT_CONFLICT`, `SSH_FORWARD_FAILED`, `SSH_TIMEOUT`,
`CORE_UNREACHABLE_OVER_TUNNEL`).

The former bare-`Jarvis` evidence remains historical. The rejected microWakeWord candidate is
`jarvis-microwakeword-synthetic-v0.1.tflite`, SHA-256
`4cfce8663c23c6e0b4292fee42573f97225325a62917c8b3930b15ee32ee648e`, trained
by the official Apache-2.0 source at commit
`4665173cd35f1cff9a61e06fc427f124766c488e`. The artifact and config remain
outside Git and are not physical acceptance evidence. The pinned
`hey_jarvis_v0.1.onnx` artifact is CC-BY-NC-SA-4.0 pretrained material
served by an Apache-2.0 engine; its exact provenance is in ADR-0018, ADR-0019,
and the migration evidence. The MFCC, backend-comparison, cascade,
and prior bare-`Jarvis` benchmarks remain historical software evidence. No
repetitive calibration is requested. No continuous heavy Whisper or paid
service may be substituted.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
