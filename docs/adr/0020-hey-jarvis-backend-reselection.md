# ADR-0020: Hey Jarvis Backend Reselection Gate

- Status: blocked — no wake backend meets the locked software gate
- Date: 2026-08-25
- Supersedes: ADR-0019's final-backend selection claim; historical evidence is retained

## Decision

The official current ESPHome microWakeWord v2 `Hey Jarvis` artifact was freshly
verified and evaluated before any rejection decision. The artifact is
`hey_jarvis.tflite` from `esphome/micro-wake-word-models`, `main` commit
`05b65922cc433c9df13e98e32a7fe520758c837e`, Git blob
`0075302434cc72a460ced0b8f6c09c69214e5cf0`, SHA-256
`21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77`.
The collection is Apache-2.0, but artifact-specific terms are not declared.
The pinned local runtime was `pymicro-wakeword==2.4.1` with
`pymicro-features==2.0.2`.

On the independent synthetic held-out corpus, microWakeWord recorded 217/504
positive detections (43.06% recall) and 262/7,268 false activations (3.60%
raw acoustic FAR, 82.6284 false activations/hour). It failed before a long
continuous acceptance run was justified. Its complete provenance and scalar
results are in `evidence/PHASE_10_WAKE_BACKEND_RESELECTION.json`.

The incumbent official openWakeWord `hey_jarvis_v0.1.onnx` plus bounded
`faster-whisper-base.en` cascade was also re-evaluated. The full held-out
result was 489/504 (97.02% recall), 75/7,268 false activations (1.03% raw
acoustic FAR, 28.9501 false activations/hour). A five-hour in-memory
continuous negative stream produced one false wake (0.2 FAPH), so it also
misses the production gate. The raw no-VAD operating point was 503/504 with
560/7,268 false activations; a bounded internal-VAD control was 39/48 with
30/516 false activations. These are measured comparison results, not a
production acceptance claim.

The locked software policy remains at least 98% recall, at most 0.25% FAR,
and at most 0.1 false wakes/hour on a continuous stream, with a preferred
99% / 0.1% / 0.1 FAPH operating point. Raw acoustic FAR and any
production-reachable FAR are reported separately. Neither candidate is
promoted, and no owner physical gate is authorized. The existing openWakeWord
cascade remains the single incumbent runtime path only; no automatic fallback
or second active backend is introduced.

## Cleanup and safety

The microWakeWord adapter, optional dependency, and benchmark script are
removed after the comparison. Their exact artifact/runtime provenance and
sanitized measurements remain in evidence and the license inventory. No raw
audio, owner recordings, credentials, transcripts, or model caches are
committed. Phase 10 activation, Core authority, Phase 8 approvals, Phase 9
Windows boundaries, and the compact three-to-five-activation owner policy are
unchanged. Phase 11 room/multi-device voice remains `NOT_STARTED`.

The next backend decision requires a new owner-approved zero-cost evaluation
and a fresh ADR; this blocked result does not authorize an owner physical
session.
