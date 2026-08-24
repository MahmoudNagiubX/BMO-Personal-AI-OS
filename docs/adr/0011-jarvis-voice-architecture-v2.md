# ADR-0011: JARVIS Voice Architecture v2

**Status:** Accepted  
**Date:** 2026-08-24  
**Supersedes:** ADR-0010 for the Phase 10 runtime activation and turn-taking details  
**Owner:** Mahmoud

## Context

The first exact-bare-`Jarvis` microWakeWord candidate was instrumented and
tested with changing tensors and genuine model output, but positive speech did
not separate from silence/noise (approximately `0.000158` score delta). The
candidate is therefore preserved as historical evidence and rejected as a
production wake detector. Paid or expiring wake services are not acceptable.

The owner locked a natural, single-device JARVIS experience on the ASUS TUF:
hands-free exact `Jarvis`, immediate keyboard activation, follow-up turns,
turn-aware endpointing, streamed safe speech presentation, and real barge-in.

## Decision

Phase 10 v2 uses the following product-owned boundaries:

- Vosk `vosk-model-small-en-us-0.15` is the current zero-cost, offline,
  grammar-bounded wake backend. The grammar is exact `jarvis` plus rejection
  handling; `Hey Jarvis` is not the production phrase. Vosk is evaluated with
  synthetic/offline positive and negative corpora before the short owner gate.
- The existing wake adapter remains the only wake-backend boundary. The
  defective microWakeWord result and prior openWakeWord result remain in the
  historical evidence; neither is silently rewritten.
- Exact `Jarvis`, double-tap Right Ctrl, and PTT all enter one activation
  router and one voice pipeline. Right Ctrl is a minimal Windows user-session
  poller for that key only and requires no administrator privilege. PTT is
  fallback/debug, not the normal UX.
- A bounded in-memory pre-roll preserves speech following a wake detection.
  Raw PCM is cleared at turn completion, interruption, failure, and sleep.
- Silero VAD remains the speech gate. Local Pipecat Smart Turn v3.x is the
  turn-end signal, with a bounded deterministic timeout fallback. Smart Turn
  never grants model or tool authority and never writes raw audio.
- The authenticated existing VENOM Core transport remains the only assistant
  path. The voice client does not call Qwen or Ollama directly. The current
  Core transport exposes a truthful final-ready response event when safe
  deltas are unavailable; the voice layer streams that response into ordered,
  semantically safe phrase/sentence TTS chunks without dropping content.
- TTS playback is cancellable. Barge-in stops only this voice playback,
  cancels queued/future phrase synthesis, and returns to the same listening
  pipeline. Voice presentation is concise, calm, multilingual, and does not
  imitate an actor.
- Qwen 3.5 4B, BGE-M3, Phase 6 identity, Phase 7 conversation authority,
  Phase 8 permission/approval/audit, and Phase 9 Windows boundaries remain
  unchanged. Qwen 3.5 9B remains optional and is not required for voice.

Phase 11 remains **NOT_STARTED**. Room microphones, room speakers,
multi-device routing, MQTT/Home Assistant voice, and distributed wake-word
deployment are outside this decision.

## Security, privacy, and licensing

All wake, VAD, STT, TTS, and playback remain local to the ASUS TUF. Idle mode
uses only bounded in-memory wake processing; full STT, Core, and model calls do
not run while sleeping. No raw audio is written to Git, the database, logs,
audit, or evidence. No cloud, subscription, AccessKey, or paid voice service
is required. Vosk, Pipecat Smart Turn, and their model licenses are recorded
in `docs/legal/LICENSE_INVENTORY.md`; artifacts remain outside Git.

Consequential actions continue through authenticated Core, exact-owner
approval, the Phase 8 authority, and the Phase 9 typed Windows satellite.
Voice never creates an unrestricted shell or direct execution path.

## Migration and rollback

The transition is a normal code/documentation commit on the existing Phase 10
branch. The Vosk model is an owner-local artifact installed outside the
repository and can be removed without changing repository history. Reverting
the Phase 10 v2 commit restores the prior adapter/runtime state while leaving
the historical microWakeWord diagnostics intact. No VENOM or Phase 11
deployment is created by this ADR.

## Validation

Governance requires the exact `Jarvis` phrase, Vosk software evidence, the
shared activation path, Smart Turn plus fallback, no-retention behavior, no
direct model bypass, preserved historical wake failures, and an explicit
`NOT_STARTED` Phase 11 boundary. A short owner physical session is permitted
only after the synthetic/offline software benchmark and full repository checks
pass.
