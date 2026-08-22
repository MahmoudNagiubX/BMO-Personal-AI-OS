# ADR-0010 - JARVIS Voice Core and Room Voice Boundary

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** Mahmoud
- **Supersedes:** The Phase 10 / Phase 11 voice sequencing in Master Plan 1.6
- **Superseded by:** None

## Context

The previous roadmap treated Phase 10 as push-to-talk voice and deferred
wake-word behavior to Phase 11. The owner has changed the required product
experience to a local, hands-free, single-device JARVIS voice core on the ASUS
TUF. This changes the active phase boundary and must be represented in the
repository source of truth before implementation.

Room and whole-home voice remain a separate distributed problem. Combining
them with the first single-device voice implementation would broaden hardware,
identity, privacy, and deployment scope without an accepted room architecture.

## Decision

### Phase 10 - JARVIS Voice Core

Phase 10 includes the ASUS TUF single-device voice path:

- local ``Jarvis`` wake word and wake-word-only idle;
- bounded VAD, local multilingual STT, and local TTS;
- hands-free natural conversation and a bounded follow-up window;
- deterministic silence timeout and explicit voice-session state machine;
- real barge-in/interruption and bounded cancellation;
- a shared local push-to-talk fallback for privacy and debugging only;
- no-retention audio defaults, bounded buffers, and cleanup proof;
- latency, thermal, memory, VRAM, and repeated-turn measurements.

Voice remains a client modality of the accepted VENOM Core identity,
conversation, ModelGateway, permission, approval, audit, and Phase 9
execution authorities. Voice must not call a model directly, approve tools, or
create a new unrestricted execution path.

### Phase 11 - Room / Multi-Device Voice

Phase 11 remains deferred and includes only later distributed voice work:

- distributed room microphones and multiple room speakers;
- room-presence routing and remote room nodes;
- ESP32/Pi room hardware and far-field microphone topology;
- whole-home voice handoff and multi-device session routing;
- room-level wake-word deployment if a later gate requires it.

Phase 11 is **NOT_STARTED** by this decision and must not be implemented as
part of Phase 10.

## Security and privacy boundaries

All audio processing in Phase 10 is local to the ASUS TUF. Idle wake-word
processing uses a bounded in-memory buffer and does not run full STT, call the
model, persist transcripts, or send audio to VENOM. Active turns send only the
resulting text through authenticated existing Core conversation authority.

No public or LAN inbound voice endpoint, cloud or paid voice service, raw
audio retention, voice biometrics, smart-home execution, or room deployment is
authorized. Consequential actions retain exact-owner approval and the existing
Phase 8/9 boundaries.

Push-to-talk is a fallback/debug path, not the normal production interaction.

## Consequences

- Phase 10 can optimize the real hands-free TUF experience without waiting for
  room hardware.
- Phase 11 retains a clean boundary for distributed microphones, speakers, and
  room routing.
- Local STT/TTS/wake-word dependencies and model/voice licenses must be
  recorded in ``docs/legal/LICENSE_INVENTORY.md`` before acceptance.
- The TUF must be measured for staged residency; heavy models are not assumed
  to coexist safely.

## Migration and rollback

The governance change is a normal Git revert. Phase 10 runtime rollback is a
normal code revert and removal of only Phase 10-owned local user artifacts.
VENOM remains the authority and is restored to its accepted release after any
temporary candidate integration test. No Phase 11 migration or deployment is
created by this ADR.

## Validation

Governance tests must reject the old active requirement that Phase 10 be
push-to-talk-only or that wake word belong exclusively to Phase 11. They must
require the explicit JARVIS Phase 10 scope, the deferred Phase 11 boundary,
and the no-audio-retention/no-direct-model-authority wording.
