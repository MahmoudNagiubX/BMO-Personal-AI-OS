# ADR-0022 — Replace custom Hey Jarvis wake stack with Rhasspy pyopen-wakeword streaming implementation

- Status: accepted for the Phase 10 wake-only reset
- Date: 2026-08-26
- Supersedes: the active wake implementation portions of ADR-0021

## Context

The prior Phase 10 path accumulated a dscripka openWakeWord candidate,
calibration thresholds, owner enrollment, a custom verifier, temporal policy,
and a Whisper wake verifier. The physical evidence showed the bottleneck before
the verifier: a valid moderate-distance owner sample scored `0.0048691` against
the candidate threshold `0.1959392`, so the verifier could never be reached.

Continuing to add filters downstream would not repair that failure. The prior
owner-verifier reports, manifests, and ADRs remain historical evidence and are
not deleted.

## Decision

Use the Apache-2.0 Rhasspy `pyopen-wakeword==1.1.0` package, reviewed at
`6bc5c5f5c9c71e46a723b6c9277b1d50f2ba13fd`, through the product-owned
`RhasspyHeyJarvisDetector`. The detector constructs
`OpenWakeWordFeatures.from_builtin()` and
`OpenWakeWord.from_builtin(Model.HEY_JARVIS)` once, then streams canonical
16 kHz mono PCM16 through eight exact 10 ms chunks for each BMO 80 ms frame.

The trigger policy follows the Apache-2.0
`wyoming-openwakeword` reference at commit
`419701f64aa936ff62a820dfeac757f1afda01d1`: threshold `0.5`, trigger level
`1`, and a two-second refractory interval. Feature and model state continue
advancing during refractory. Detector reset is limited to runtime/new sleeping
lifecycle boundaries. Wyoming networking is not introduced.

BMO state remains authoritative: the wake detector is invoked only while
`SLEEPING`; conversational VAD, STT, TTS, Core, pre-roll, activation routing,
and tool authority are unchanged. The owner verifier and Whisper wake verifier
are not in the active path, and no enrollment is required for this migration.

## Consequences

The built-in `hey_jarvis.tflite` model is pinned by its installed package
identity and SHA-256
`14bff778604985e1b5c19f0f7bbe477a69cf281d8db34b232b3b972411f710e2`.
Input bytes remain bounded and in memory only; no audio, owner profile, or
credential is stored. The new software evidence proves direct-reference parity
and deterministic lifecycle/state behavior, but the compact ASUS TUF physical
probe remains required before any wake acceptance claim.

Phase 11 room/multi-device voice remains `NOT_STARTED`.
