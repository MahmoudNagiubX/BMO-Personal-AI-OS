# ADR-0024 - Full-duplex JARVIS conversation coordinator

- **Status:** Accepted for Phase 10 implementation
- **Date:** 2026-08-26
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

The Phase 10 voice pipeline already owns wake detection, local VAD, final
speech recognition, authenticated Core submission, local TTS, and playback.
Those boundaries need one live coordinator so capture can continue during
assistant speech, natural pauses do not cause partial submissions, and a
confirmed owner interruption cannot resume stale playback. The coordinator
must not create a second model, Core, tool, approval, or audio-retention path.

## Decision

Add `JarvisConversationLoop` as the single product-owned live-session
coordinator around `JarvisVoicePipeline`.

- A single worker serializes final STT/Core/TTS turns. Only a completed final
  turn is submitted to authenticated VENOM Core, exactly once.
- Wake capture is routed to the existing pipeline only in `SLEEPING`. Right
  Ctrl double-tap, wake detection, and PTT enter the same downstream session.
- Silero VAD determines speech presence; the existing local Smart Turn adapter
  determines natural end-of-turn when available, with a bounded deterministic
  timeout fallback.
- During `SPEAKING`, bounded microphone observations confirm an interruption
  within 120-240 ms. Playback and queued TTS work are cancelled, and only a
  bounded in-memory interruption window is preserved for the next turn.
- Follow-up listening remains in the same session and returns to wake-word-only
  `SLEEPING` after the existing timeout. Assistant playback never arms wake
  inference or creates a barge-in by itself.
- State transitions, one-turn submission counts, cancellation latency, and
  privacy outcomes are exposed as scalar diagnostics only.

## Rationale

The coordinator keeps concurrency policy and lifecycle state outside framework
adapters while reusing the accepted pipeline's Core and authority boundaries.
A single worker prevents concurrent final turns without introducing a broker
or a new service. Bounded in-memory buffers make interruption responsive while
preserving the no-retention default.

## Consequences

### Positive

- Natural pauses, follow-up turns, self-correction, and real barge-in have one
  deterministic lifecycle owner.
- Partial speech cannot reach Core, and an interrupted response cannot silently
  transition the session back to follow-up mode.
- Synthetic coverage can prove exactly-once Core submission and no playback
  self-trigger without owner audio or physical deployment.

### Negative / trade-offs

- Final STT/Core/TTS work is serialized, so a second turn waits for the first
  turn's bounded cancellation and cleanup.
- Physical microphone, resource, thermal, and model-residency acceptance still
  require a later owner session after the existing wake software gate.

## Security and privacy impact

No model or tool is called directly by the coordinator. All conversational
requests remain authenticated Core requests, consequential actions remain
behind Phase 8/9 authority, and no partial text is submitted. Audio exists
only in bounded process memory and is cleared during completion, interruption,
timeout, failure, and close; evidence contains scalar metrics only.

## Migration and rollback

The local runtime exposes `build_local_conversation_loop` while retaining
`build_local_runtime` for existing callers. Reverting this Phase 10 commit
restores the prior pipeline-only construction without changing identity,
conversation, model, tool, or deployment data. No VENOM or Phase 11 deployment
is part of this change.

## Validation

The synthetic Phase 10 suite covers normal and incomplete turns, hesitation,
self-correction, pre-roll, Right Ctrl and PTT activation, follow-up and
timeout, barge-in, playback isolation, STT failure after interruption,
multilingual text, state history, closed-loop cleanup, and one end-to-end
exactly-once lifecycle. Full repository validation and exact-head hosted CI
remain required before independent review.
