# ADR-0018: Hey Jarvis Primary Wake Phrase Migration

**Status:** Accepted for Phase 10 implementation; software gate pending

**Date:** 2026-08-25

## Context

The owner changed the Phase 10 hands-free product phrase from the historical
bare `Jarvis` phrase to the exact production phrase `Hey Jarvis`. This is a
phrase migration inside the existing single-device ASUS TUF voice pipeline,
not a new room or multi-device architecture. The earlier bare-`Jarvis`
physical and software results remain historical evidence and must not be
rewritten as evidence for the new phrase.

The selected zero-cost local candidate is the official pretrained
openWakeWord `hey_jarvis` artifact. It is evaluated with production-equivalent
16 kHz mono PCM16 capture delivered in bounded 80 ms frames. A bounded local
faster-whisper `base.en` verifier may be enabled after a candidate trigger;
neither wake stage may call Core, Qwen, tools, or the Windows Satellite while
the device is sleeping.

## Decision

Use the exact `Hey Jarvis` phrase as the one canonical hands-free phrase. Keep the phrase in a
product-owned constant and require exact normalized leading-token matching for
the verifier and command pre-roll. Bare `Jarvis`, `Hi Jarvis`, `Hello Jarvis`,
and other variants are non-production negatives after this migration.

The active evaluation configuration is:

- repository: `https://github.com/dscripka/openWakeWord`;
- revision: `v0.5.1`;
- tag commit: `1eec2158c5c54150ac5f4c15065adacb1003b1e7`;
- artifact: `hey_jarvis_v0.1.onnx`;
- SHA-256: `94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb`;
- model license: Apache-2.0;
- runtime: `openwakeword==0.6.0` with the pinned local ONNX runtime.

The candidate is tested first as a single stage. If it does not meet the
software gate, the bounded candidate-plus-verifier cascade is evaluated. The
minimum software gate is 98% held-out recall and at most 0.25% false
activation rate; the preferred operating point is 99% recall and at most
0.1% FAR, with no assistant-playback production wake transitions. A blocked
software gate does not authorize owner physical testing.

The compact owner gate, after the software gate passes, is three to five
intended activations and representative negatives. The former 20-round owner
calibration is historical only. Right-Ctrl double-tap, PTT, Smart Turn,
pre-roll, follow-up, barge-in, and the authenticated Core/Phase 8/9 path are
unchanged and share the same pipeline.

## Consequences

`JarvisVoicePipeline` strips one leading canonical `Hey Jarvis` phrase before
authenticated Core submission, preserving a natural one-breath command such
as `Hey Jarvis open VS Code`. Sleeping mode remains lightweight and local; no
raw audio, credential, transcript, or recording is committed or retained.

The official artifact provenance and checksum are part of the runtime
configuration and sanitized migration evidence. The previous bare-`Jarvis`
artifacts and physical results remain in their historical reports. No paid
service, AccessKey, cloud fallback, direct model call, unrestricted tool, or
Phase 11 room deployment is introduced.

## Migration and rollback

The normal branch remains `phase-10/jarvis-voice-core`. The launcher verifies
the official local artifact checksum before starting the owner-local runner.
Rollback means reverting the Phase 10 migration commit and restoring the
previous historical runtime configuration; it does not rewrite or delete
historical evidence. A failed software gate stops at the repository boundary
until a later owner decision selects a different free local backend.

## Boundary

Phase 10 remains ASUS TUF single-device JARVIS Voice Core. Phase 11 room,
multi-device, and distributed voice remains `NOT_STARTED`.
