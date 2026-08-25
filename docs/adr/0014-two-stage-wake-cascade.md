# ADR-0014: Two-Stage Wake Cascade Software Gate

**Status:** Blocked — no cascade is authorized for owner enrollment or physical
acceptance
**Date:** 2026-08-25  
**Supersedes:** No prior decision; this records the bounded follow-up to
ADR-0013  
**Owner:** Mahmoud

## Context

The exact production phrase remains bare `Jarvis`, and the zero-cost policy
rejects paid wake-word services. The previous BMO MFCC/DTW and WakeForge
single-stage comparison did not justify owner enrollment. The next bounded
software experiment was a two-stage local cascade:

```text
bounded speech/VAD -> candidate detector -> local exact-phrase verifier
-> shared ActivationRouter
```

The candidate stages were the BMO-owned MFCC/DTW detector and the audited
WakeForge reference. The verifier was the MIT-licensed
`Systran/faster-whisper-small` model at revision
`536b0662742c02347bc0e980a01041f333bce120`, used locally through the existing
product-owned speech adapter. The benchmark used a held-out synthetic corpus
of 60 positive and 310 negative attempts across normal English, hard
phonetic, Arabic, mixed, background-conversation, and silence/noise cases.
No owner audio, raw audio, remote dataset, cloud TTS, or retained temporary
audio was used.

## Decision

The two-stage cascade is **blocked at the software operating point**. The
best observed result for BMO MFCC/DTW → Whisper, WakeForge → Whisper, and the
VAD → Whisper control was 56/60 positive detections (93.33% recall) with
0/310 false activations. The required software target is at least 95% recall
with at most 0.5% false activation rate, so no winner is selected and no
threshold is promoted. The CPU verifier measured approximately 4996.597 ms
p50 and 5865.029 ms p95 candidate-to-verification latency. A CUDA attempt was
blocked by a missing `cublas64_12.dll`; no CUDA performance or residency
claim is made.

The result does not authorize owner enrollment, another physical session, or
a production backend switch. Historical openWakeWord, microWakeWord, Vosk,
Sherpa KWS, PocketSphinx, local-wake embedding, BMO comparison, and WakeForge
evidence remain preserved. The existing exact-`Jarvis` product adapter and
privacy boundary remain unchanged. Phase 11 remains `NOT_STARTED`.

## Consequences and next gate

The Phase 10 owner gate remains pending. Future work needs a measured,
license-clean software improvement that reaches the target before owner audio
or a physical acceptance session is requested. Any future verifier must keep
sleeping mode bounded and local; full STT/LLM inference must not run while the
system is idle. The cascade experiment is evaluation-only and introduces no
new production dependency or network listener.

## Evidence and rollback

Sanitized scalar evidence is recorded in
`docs/phase_reports/evidence/PHASE_10_WAKE_CASCADE.json`. The benchmark runner
was tested at implementation commit
`b5dcd69bbd235d63f8ae0c66a2f0843428a8977c`. The v2 summary points to that
artifact without self-attesting final exact-head CI; exact-head CI remains an
external GitHub governance check. Rollback is documentation-only: remove the
cascade evidence/ADR and restore the prior ADR-0013 evidence state. No
production model, wake backend, or owner profile is changed.
