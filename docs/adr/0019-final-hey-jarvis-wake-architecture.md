# ADR-0019: Final Hey Jarvis Wake Architecture and Experiment Cleanup

- Status: accepted for software implementation; owner physical gate blocked
- Date: 2026-08-25
- Supersedes: the runnable candidate experiments described by ADR-0012,
  ADR-0013, and ADR-0014

## Decision

Phase 10 uses one production wake architecture:

\`16 kHz PCM -> official openWakeWord Hey Jarvis candidate -> bounded local
faster-whisper exact-prefix verifier -> the shared JARVIS state/session pipeline\`

The candidate is the pinned \`hey_jarvis_v0.1.onnx\` artifact from
\`dscripka/openWakeWord\`, revision \`v0.5.1\`, commit
\`1eec2158c5c54150ac5f4c15065adacb1003b1e7\`, SHA-256
\`94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb\`.
The openWakeWord engine is Apache-2.0. The pretrained artifact is
CC-BY-NC-SA-4.0 and is not distribution-cleared by this repository.
The verifier is the pinned local \`base.en\` faster-whisper model under its
MIT license.

The candidate is tuned only on synthetic/offline held-out corpora. The
accepted policy must record threshold, candidate VAD threshold, temporal mode,
window, required hits, and deactivation hysteresis. A continuous stream
measurement is required before the software gate can pass; a long high-score
run counts as one event until the score falls below the deactivation
threshold.

The owner physical session is intentionally short: three to five intended
\`Hey Jarvis\` activations, representative English/Arabic/background negatives,
one natural single-utterance command, Right-Ctrl double-tap through the same
router, natural-pause Smart Turn, follow-up, barge-in, sleep, PTT fallback,
privacy, resource, and regression checks. The historical 20-round calibration
is retained only as evidence and is not an active acceptance requirement.

## Rejected or historical paths

Bare \`Jarvis\`, microWakeWord, Vosk, PocketSphinx, Sherpa KWS, personalized
MFCC/DTW, WakeForge, and the associated training/debug/comparison scripts are
historical evidence only. Their runnable production adapters, optional
dependencies, and owner-facing experiment scripts are removed. Historical
ADRs and sanitized evidence remain immutable audit context.

The model output is only a wake candidate. It cannot call Core, tools, or
executors. All active conversation behavior continues through authenticated
Core, Phase 8 approval, and Phase 9 Windows Satellite boundaries.

## Consequences and rollback

This decision keeps one auditable backend and makes false-activation policy
explicit, while retaining an exact rollback point in Git before this ADR.
Rollback means restoring the previous Phase 10 commit and its evidence; it
does not re-enable a retired backend as a hidden production fallback.

No raw audio, owner recordings, transcripts, credentials, or model caches are
committed. Phase 11 room/multi-device voice remains \`NOT_STARTED\`.

## Current acceptance state

The prior authoritative \`e103a62523dcfa1253c449775492e34a4497359d\` run measured
110/120 positive detections, 24/3540 false activations, and 19.6721 false
activations/hour. That does not meet the candidate/verifier software target,
and the corrected continuous-stream gate has not been run in this workspace
because the required local TTS/corpus artifacts are absent. Therefore the
owner physical gate is not authorized by this ADR.
