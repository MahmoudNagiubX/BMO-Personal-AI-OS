# ADR-0015: English Wake Verifier Optimization Gate

**Status:** Blocked - no verifier is authorized for owner physical acceptance  
**Date:** 2026-08-25  
**Supersedes:** ADR-0014 for the verifier-specific software gate only  
**Owner:** Mahmoud

## Context

The earlier two-stage cascade reached 56/60 recall with 0/310 false
activations, below the required software target. This bounded follow-up kept
the exact bare `Jarvis` phrase and evaluated a dedicated short-phrase English
faster-whisper verifier separate from conversational multilingual STT.

The verifier contract is local and deterministic: `language=en`,
`task=transcribe`, no previous-text conditioning, no timestamps, zero
temperature, no forced prefix, and only beam sizes 1, 3, or 5 with either no
hotword or the exact `Jarvis` hotword. The tested models were the official
Systran faster-whisper `tiny.en`, `base.en`, and `small.en` repositories at
the pinned revisions recorded in the sanitized evidence. All are MIT
licensed. The CUDA runtime was loaded from approved local artifacts:
CUDA 12 runtime/BLAS from the accepted llama.cpp bundle and cuDNN 9 from the
pinned CTranslate2 wheel.

The synthetic corpus was generated locally from the existing evaluation-only
Piper/Sherpa assets. It included positive bare-phrase samples, normal English,
hard phonetics, Arabic, mixed speech, background conversation, silence/noise,
media playback, assistant/JARVIS playback, and fan/keyboard noise. No owner
audio, raw audio, credentials, remote dataset, cloud TTS, or retained
temporary audio was used.

## Decision

The verifier optimization remains **blocked**. A configuration sweep across
the three model sizes, candidate stages, three audio-conditioning variants,
and beams 1/3/5 with both hotword settings produced no operating point at the
required >=95% recall and <=0.5% false-activation rate.

The final independent held-out run used base.en with BMO MFCC/DTW, original
audio conditioning, beam 1, and no hotword. It recorded 144/150 detections
(96.0% recall) and 45/1,075 false activations (4.19% FAR). All 45 false
activations were in assistant/JARVIS playback; six positive misses were
classified as wrong-first-token. The best warm verifier latency was 38.601 ms
p50 and 57.185 ms p95. GPU loading passed without OOM or display-driver reset;
the measured base.en run used 1,633,681,408 bytes of VRAM and reached 58 C.

This result does not authorize owner enrollment or another physical session.
The 45 assistant-playback false activations identify a remaining self-trigger
boundary in addition to the verifier's linguistic misses. No model is
promoted to production, and no automatic fallback or paid wake service is
introduced. Phase 11 remains `NOT_STARTED`.

## Consequences and next gate

The product-owned wake adapter, exact phrase, authenticated Core path, dual
activation, privacy boundary, and one-heavy-model policy remain unchanged.
The next Phase 10 work must address playback/self-trigger suppression and/or
obtain a materially better license-clean local verifier before requesting the
single compact owner session. It must retain the >=95% / <=0.5% software
gate and the sanitized held-out evidence requirement.

## Evidence and rollback

Sanitized scalar evidence is recorded in
`docs/phase_reports/evidence/PHASE_10_WAKE_VERIFIER_OPTIMIZATION.json` and is
validated by `scripts/phase_10/validate_evidence.py`. The implementation and
CUDA loader were tested at commit
`e9de3ead8b1deccf67e135ab0f84e02ee805ce30`; final exact-head CI remains an
external GitHub governance check and is not self-attested here.

Rollback is documentation/evidence-only: remove this ADR, the optimization
evidence, and the dedicated verifier benchmark, then restore ADR-0014's
blocked cascade evidence. No owner profile, physical host, public listener,
Phase 9 boundary, or Phase 11 state is changed.
