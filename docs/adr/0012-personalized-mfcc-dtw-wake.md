# ADR-0012: Personalized MFCC/DTW Wake Detection

**Status:** Accepted  
**Date:** 2026-08-25  
**Supersedes:** ADR-0011 wake-backend selection only  
**Owner:** Mahmoud

## Context

The official zero-cost wake candidates were evaluated without retaining owner
audio. The microWakeWord candidate produced genuine model output but only
approximately `0.000158` positive/noise separation. The official Sherpa KWS
artifact produced no synthetic bare-`Jarvis` detections. Vosk and PocketSphinx
were preserved as historical evidence but did not meet the final wake gate.

The `st-matskevich/local-wake` code is MIT-licensed, but its bundled
`speech-embedding.onnx` has no model-specific license, exact upstream revision,
or conversion provenance. It is not an accepted BMO dependency or runtime
artifact. The local-wake neural path is therefore rejected without owner
enrollment.

## Decision

The selected backend is personalized MFCC/DTW. Phase 10 uses a BMO-owned
`PersonalizedMfccDtwWakeWordDetector` behind the
existing wake adapter. It uses the already-pinned NumPy runtime for a bounded
16 kHz MFCC frontend and normalized subsequence DTW. The implementation uses
no pretrained wake or embedding weights; no such weights are loaded.
Local-wake and Rhasspy Raven are implementation
references only; required attribution and their licenses are recorded in the
license inventory.

The detector accepts an explicit local derived-template profile containing
three or four owner recordings converted to MFCC matrices. Raw PCM exists only
in bounded memory during enrollment/streaming, is cleared after extraction or
detection, and is never written to Git, evidence, logs, audit, or the database.
The profile includes only feature matrices, feature configuration, an exact
`Jarvis` identity, `raw_audio_retained=false`, and a SHA-256 integrity field.

Subsequence matching is bounded to the speech-onset prefix so `Jarvis open VS
Code` remains one utterance while `Hey Jarvis` is not treated as the production
phrase. The detector requires a multi-template vote and a fixed local threshold
selected from non-owner viability evidence. Final recall and false-activation
acceptance remains a physical owner gate after one enrollment session.

Right-Ctrl double-tap, PTT, VAD, Smart Turn, STT, authenticated Core,
approval/audit authority, TTS, barge-in, Qwen 4B, optional Qwen 9B, and the
Phase 11 boundary remain unchanged.

## Migration and rollback

The runtime backend name is `personalized_mfcc_dtw` and requires an explicit
profile path. The owner-local enrollment command writes only a derived profile
outside the repository. Removing that profile disables hands-free wake without
altering other voice activation paths. Reverting this normal commit restores
the previous adapter/runtime state and leaves all rejected-backend evidence
historical.

## Validation

Before owner enrollment, the synthetic viability benchmark must prove bounded
MFCC extraction, three-template enrollment, streaming detection, command
following, finite CPU behavior, and no raw-audio retention. Its hard-negative
results are reported as viability evidence and are not claimed as the final
personalized acceptance gate. After software validation, one owner session may
provide at most four bare-`Jarvis` enrollment samples; no repetitive
calibration is authorized.

Phase 11 remains **NOT_STARTED**.
