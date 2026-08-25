# ADR-0017: Production-Equivalent Streaming Wake Path

**Status:** Accepted — software gate passed; compact owner physical retest ready  
**Date:** 2026-08-25  
**Supersedes:** ADR-0016 benchmark/runtime timing claims only  
**Owner:** Mahmoud

## Context

The first real `vad_whisper` ASUS TUF Stage-A result was 0/3 wake detections
with zero false activations. Source inspection found that the physical
`SoundDeviceBackend` emits approximately 80 ms, 16 kHz mono PCM16 frames while
the prior stateful benchmark passed each synthetic utterance as one whole
`AudioFrame`. The earlier recall therefore was not evidence for the physical
streaming cadence. The owner audio result is preserved as pre-fix historical
evidence and is not treated as a pronunciation failure.

## Decision

The product-owned `WakeCascadeDetector` now uses a bounded streaming state:

- a rolling 640 ms VAD window identifies speech onset/activity;
- the first exact-phrase verifier call waits for 320 ms of accumulated speech;
- the initial verifier window is 320 ms, retries occur every 160 ms, and no
  candidate receives more than four verifier calls;
- retries receive the accumulated leading candidate window so the `Jarvis`
  prefix is not lost to a sliding-tail window;
- candidate accumulation is capped at 1.8 seconds and resets on bounded
  speech timeout, acceptance, rejection budget, sleep, interruption, or trial
  cleanup;
- the benchmark and physical Stage-A harness feed `on_capture_frame` with the
  same 80 ms cadence as production, never `on_wake_frame` or a whole utterance.

The wake path remains local and memory-only. Full STT, Core, and model calls
remain disarmed while sleeping except for the bounded local wake verifier;
voice still enters authenticated Core after activation and cannot execute a
tool directly.

## Evidence and acceptance

The production-equivalent synthetic gate at implementation commit
`beadb55f9d4221ffa3b876edfe4c38380cafc820` evaluated all twelve bounded
window/cadence configurations. The selected 320 ms / 160 ms profile recorded
35/36 (97.22%) in the timing subset with 0/258 external false activations, and
149/150 (99.33%) sleeping recall with 0/975 external false activations on the
full held-out lifecycle corpus. Speaking and follow-up assistant playback
produced zero verifier calls and zero wake transitions; barge-in passed 20/20
and single-utterance pre-roll preservation passed 19/20. Scalar evidence is
in `evidence/PHASE_10_STREAMING_WAKE_PATH.json`.

The prior whole-utterance artifact remains in
`evidence/PHASE_10_STATEFUL_WAKE_ISOLATION.json` with an explicit
`whole_utterance_frame_pre_fix` measurement mode and no physical-readiness
claim. The owner's pre-fix physical 0/3 result remains in the physical
evidence file and must not be rewritten as a pass.

## Consequences and rollback

The software-only target of at least 95% recall and at most 0.5% external FAR
is now met under realistic capture cadence. One compact owner physical retest
is permitted; no repetitive 20-round calibration is requested. Reverting the
normal implementation commit restores the earlier cascade and its historical
blocked state. Phase 11 remains `NOT_STARTED`.
