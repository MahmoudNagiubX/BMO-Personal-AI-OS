# Phase 10 — JARVIS Voice Core Report

## Status

The owner rejected paid/subscription wake-word services, including Picovoice
Porcupine. Controlled diagnostics proved the historical microWakeWord tensors
and output were genuine, but positive/noise separation was only approximately
`0.000158`; that candidate remains historical evidence. The owner then
authorized the exact `Hey Jarvis` phrase. ADR-0018 records the official
openWakeWord artifact, its provenance/checksum, and the bounded cascade gate.
The previous bare-`Jarvis` physical evidence remains historical only.

The corrective backend reselection evaluated the current official ESPHome
microWakeWord v2 artifact before rejecting it. Its independent held-out result
was 217/504 recall (43.06%) with 262/7,268 false activations (3.60% raw FAR).
The incumbent openWakeWord plus faster-whisper cascade reached 489/504 recall
(97.02%) with 75/7,268 false activations (1.03% raw FAR), and its five-hour
continuous negative stream recorded one false wake (0.2 FAPH). Neither result
meets the locked 98% / 0.25% / 0.1 FAPH software gate. ADR-0020 records this
historical comparison; ADR-0022 records the superseded Rhasspy streaming reset.

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

The active wake implementation is now the product-owned speech-gated ASR
detector. Silero VAD creates only a bounded in-memory speech candidate, then
the pinned faster-whisper `base.en` CPU `int8` recognizer and exact-prefix
verifier decide `Hey Jarvis`; no KWS candidate runs before ASR. The owner
verifier, Rhasspy, and other prior wake paths remain historical, with no
enrollment required by the active path. The current bounded streaming
diagnostic is recorded honestly in
`evidence/PHASE_10_SPEECH_GATED_WAKE.json`: 5/6 positive detections (83.33%)
and 1/21 negative false activations (4.76%), including one hard-phonetic
false activation. This does not meet the 98% recall / 0.25% FAR software gate,
so the owner physical probe is not authorized. See ADR-0023 and the evidence
file for the bounded configuration and sanitized measurements.

## Full-duplex conversation software gate

The full-duplex implementation at the `JarvisConversationLoop` coordinator is
software-complete. It wraps the accepted pipeline with one serialized final
turn worker, sleeping-only wake capture, Silero VAD plus Smart Turn and a
bounded timeout fallback, cancellable phrase-level TTS, bounded barge-in
confirmation, same-session follow-up listening, and scalar lifecycle metrics.
The physical runner now constructs this coordinator through
`build_local_conversation_loop`, delivers bounded live microphone frames through
`loop.on_frame`, and performs barge-in through the coordinator rather than a
manual pipeline call. It submits only one final transcript per completed turn
and never executes a tool or model directly.

The deterministic Phase 10 full-duplex suite passes 15/15 scenarios, including
an incomplete natural pause, self-correction, wake pre-roll, Right-Ctrl and
PTT activation, follow-up without a second wake phrase, silence timeout,
self-playback isolation, playback-only echo leakage suppression, STT failure
after barge-in, mixed-language text, state history, closed-loop cleanup, and an
exactly-once interrupted lifecycle.
The complete targeted voice/state/privacy set passes 35/35. Sanitized scalar
evidence is in `evidence/PHASE_10_FULL_DUPLEX_CONVERSATION.json` and keeps
final exact-head CI as an external governance check.

This is a software gate only. Physical ASUS TUF microphone, thermal/resource,
wake, multilingual speech, TTS, Phase 9 regression, and Qwen 4B acceptance
remain pending behind the existing wake software boundary. Phase 11 remains
`NOT_STARTED`.

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

The current active design is exactly one product-owned speech-gated ASR
detector using Silero VAD and the pinned `base.en` CPU `int8` verifier. It is
not physical-acceptance-ready until the compact owner probe passes. The prior
Rhasspy, openWakeWord, and owner-verifier paths remain historical evidence.
The candidate and verification bounds are deterministic and bounded; the
software gate is established by the new synthetic benchmark. The owner gate is compact: three to five intended
activations plus representative negatives, one natural pre-roll command,
Right-Ctrl double-tap through the shared router, Smart Turn, follow-up,
barge-in, sleep, PTT, privacy, resource, and Phase 9/Qwen regressions. The
former 20-round owner calibration is historical only.

The fresh held-out cascade run at implementation commit
`a9ec14cf014c1413ed17f2aa641723ec75a5dd80` measured 489/504 recall (97.02%),
75/7,268 false activations (1.03%), and 28.9501 false activations/hour.
The five-hour continuous raw acoustic stream measured one false wake (0.2
FAPH). Those incumbent results remain historical. The active speech-gated
diagnostic is separately recorded and is currently below the software gate,
so no owner physical session is authorized. The official microWakeWord comparison and complete
provenance are in `evidence/PHASE_10_WAKE_BACKEND_RESELECTION.json`; the
updated incumbent evidence is in `evidence/PHASE_10_HEY_JARVIS_FINAL.json`;
ADR-0020 records the decision.

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
19/20 single-utterance pre-roll preservation. That streaming artifact is
historical evidence only; the later backend reselection gate supersedes its
readiness claim. See `evidence/PHASE_10_STREAMING_WAKE_PATH.json`, ADR-0017,
and ADR-0020.

## Physical gate

The backend reselection software gate is the current acceptance boundary. The
fresh comparison used 504 positives and 7,268 negatives for each full
candidate evaluation. MicroWakeWord recorded 217/504 recall and 262/7,268
false activations; the openWakeWord cascade recorded 489/504 recall and
75/7,268 false activations, followed by one false wake in a five-hour stream.
Both miss the locked recall/FAR/continuous-stream thresholds, so the software
gate is blocked and does not authorize owner audio. Physical evidence is
intentionally pending. The bounded runner records only
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
calibrated measurable floor is always sent to the active manifest-verified wake detector; only
capture below that floor is recorded as `NO_AUDIO`, while an inference miss is
recorded as a `WAKE_MISS`. The three core activations are the acceptance gate;
quiet and faster variants are optional robustness measurements.
The loopback launcher (`run_local_acceptance.ps1`) manages the SSH tunnel to the
current VENOM host from `BMO_VENOM_HOST` (default `192.162.1.28`) with strict
known-host checking and a non-interactive identity check requiring `venom-server` /
`venom`. Core remains loopback-only through the TUF local forward. It uses a bounded
20-second readiness deadline exceeding ConnectTimeout, preflights
local port 18000 to reuse valid existing tunnels or reject conflicting listeners,
verifies unauthenticated `/health/live` reachability before invoking physical acceptance,
and surfaces categorized sanitized diagnostics (`SSH_AUTH_FAILED`, `SSH_HOST_KEY_FAILED`,
`SSH_HOST_IDENTITY_FAILED`, `SSH_HOST_IDENTITY_MISMATCH`,
`SSH_HOST_UNREACHABLE`, `LOCAL_PORT_CONFLICT`, `SSH_FORWARD_FAILED`, `SSH_TIMEOUT`,
`CORE_UNREACHABLE_OVER_TUNNEL`).
It prints `OWNER_EVIDENCE_EDIT_PRESERVED` when the canonical evidence file is dirty,
and always writes physical-session output to the dedicated
`evidence/PHASE_10_PHYSICAL_CONVERSATION_LOCAL.json` checkpoint. Existing dedicated
output is never overwritten unless it is a same-head Stage-A checkpoint explicitly
resumed. Physical barge-in evidence reports the coordinator's
`cancel_latency_p50_ms`/`cancel_latency_p95_ms`; any capture-start observation is
named separately and is not called cancellation latency.

### VENOM Core connectivity recovery

The verified current VENOM host is `192.162.1.28` (`venom-server` / `venom`),
with strict key authentication and no password requirement. The existing
baseline Core release `24297a9c8ce8ce8d386874949aa3d87e0881d9cc` was intact;
the outage was caused by `bmo-core.service` being disabled and inactive, not by
an invalid release, missing runtime, or database outage. Enabling the existing
user unit restored Core and produced `/health/live`, `/health/ready`, and
`/version` success on `127.0.0.1:8000`; the deployed build SHA remains the
accepted baseline. PostgreSQL remains the loopback-only `bmo-postgres`
container on `127.0.0.1:5432`. A closed/reopened SSH-session check retained
Core health with `Linger=no`, so no privileged Linger change was made. The
deployment and rollback scripts now re-enable `bmo-core` before restart so this
failure mode is reproducibly prevented.

The former bare-`Jarvis` evidence remains historical. The rejected custom and
official microWakeWord candidates are historical only; their provenance and
scalar results are recorded in ADR-0020 and
`evidence/PHASE_10_WAKE_BACKEND_RESELECTION.json`. The rejected custom
microWakeWord candidate is
`jarvis-microwakeword-synthetic-v0.1.tflite`, SHA-256
`4cfce8663c23c6e0b4292fee42573f97225325a62917c8b3930b15ee32ee648e`, trained
by the official Apache-2.0 source at commit
`4665173cd35f1cff9a61e06fc427f124766c488e`. The artifact and config remain
outside Git and are not physical acceptance evidence. The pinned
`hey_jarvis_v0.1.onnx` artifact is CC-BY-NC-SA-4.0 pretrained material
served by an Apache-2.0 engine; its exact provenance is in ADR-0018, ADR-0019,
ADR-0020, and the migration evidence. The MFCC, backend-comparison, cascade,
and prior bare-`Jarvis` benchmarks remain historical software evidence. No
repetitive calibration is requested. No continuous heavy Whisper or paid
service may be substituted.

### Historical owner-verifier enrollment contract correction

The first local enrollment harness run is preserved as scalar-only historical
evidence in `evidence/PHASE_10_OWNER_VERIFIER.json`: it trained an artifact,
but its two reserved positives produced zero detections and its measured
levels ranged from `0.000286/0.003357` to `0.016949/0.147369` RMS/peak. This
is an enrollment/calibration contract failure, not a wake reliability result.
No raw owner audio, artifact, or secret is in the repository. The replacement
harness captures an ambient baseline first, permits one scenario-specific
recapture only when capture is too close to that baseline, uses 2.1-second
positive clips, and partitions normal speech (10 s train/5 s holdout) and
ambient sound (4 s train/3 s holdout) without overlap. A derived profile is
always local and provisional; production loading requires a manifest-derived
held-out acceptance threshold and has no hard-coded `.5` verifier threshold.
Internal openWakeWord VAD remains disabled because its prior regression is
historical evidence. Owner re-enrollment is intentionally paused until the
corrected harness and its automated gates have passed.

The second enrollment attempt passed the dynamic audio-quality checks and
captured all five bounded clips, but no verifier artifact was produced: the
pinned upstream helper filtered positive frames with its hidden `0.5` default.
This is recorded as `upstream_positive_feature_extraction_threshold`, not as a
physical wake, microphone, or owner-pronunciation failure. The corrective
trainer now consumes a calibrated base threshold, uses production-like
temporary ambient pre-roll, and rejects any positive that does not reach the
base candidate before training.

The owner-free broad calibration then evaluated 504 independent positive
utterances and 7,268 independent negatives through the production streaming
path. It selected base invocation threshold `0.1959392`, with 502/504
candidate recall (`0.996`) and 1,084/7,268 candidate false events (`0.1491`).
This scalar diagnostic is intentionally upstream of the owner verifier and does
not authorize owner enrollment or the physical gate; the internal
OpenWakeWord VAD remained disabled.

### Superseded Rhasspy wake reset

ADR-0022 was a superseded migration and is retained for audit. Its
in-process `pyopen-wakeword==1.1.0` streaming adapter. The built-in
`Model.HEY_JARVIS` model is streamed through persistent feature and wake state
using eight 10 ms PCM16 chunks per BMO 80 ms frame. The mature defaults are
threshold `0.5`, trigger level `1`, and a two-second refractory period.
Direct-reference parity, lifecycle, chunking, state-gating, pre-roll, and
privacy tests pass. The installed model digest and reviewed upstream commits
are recorded in `evidence/PHASE_10_RHASSPY_WAKE_CORE.json`; its negative-only
synthetic smoke is not an acoustic recall claim. The owner-free benchmark
`scripts/phase_10/benchmark_rhasspy_hey_jarvis.py` accepts local WAV corpora
without writing them or its results. The compact owner probe uses
three positive and five representative negative cases, with no enrollment.

### Active speech-gated ASR wake path

ADR-0023 is the active architecture. The owner-free benchmark
`scripts/phase_10/benchmark_speech_gated_wake.py` uses seeded synthetic local
Piper/Sherpa samples, tests the bounded VAD -> faster-whisper path, and writes
only scalar metrics. The selected production configuration is `base.en` on
CPU with `int8`, beam size 1, and hotwords disabled. The current bounded
streaming diagnostic is measured but blocked at 83.33% recall and 4.76% FAR;
it is not a complete acceptance corpus and does not authorize a physical
owner probe. Its evidence identifies the tested implementation commit and
leaves final exact-head CI as an external governance condition.

## Safety and boundary

No physical host mutation, public network exposure, Phase 11 work, cloud
fallback, raw-audio retention, or tool execution is part of this branch.
