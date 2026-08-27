# ADR-0013: WakeForge Comparative Evaluation Before Owner Enrollment

**Status:** Blocked — no wake backend is authorized for owner enrollment
**Date:** 2026-08-25  
**Supersedes:** No prior decision; this records a pre-enrollment gate for ADR-0012  
**Owner:** Mahmoud

## Context

The current BMO-owned MFCC/normalized-subsequence-DTW implementation was
viable on a small synthetic check, but its 10/20 result was not sufficient to
consume a physical owner enrollment session. The next approved zero-cost
comparison was WakeForge's lightweight local MFCC path, audited at
`1adcf4c40b1a3b9e18446fcbb71088ba2a0504c7`. The OVOS WakeForge plugin at
`a9df8ca94453c160eddd99381ba8c95576f74026` and Dinkum listener at
`4d44ce62d4b90eb59be95dff563a4b1893d31ca3` were reviewed as Apache-2.0
references only.

WakeForge's default data-generation path is not adopted: it can download
mixed Hugging Face datasets, discover TTS providers, use optional voice
conversion assets, and consume pre-exported feature artifacts. The comparison
therefore used only a local MFCC extractor, local generated Piper speech, no
remote datasets, no cloud TTS, no voice conversion, and no remote feature
artifact. The local English Lessac model points to a research-only Blizzard
2013 license, and the local Arabic model points to a source repository without
a clear SPDX license; both are evaluation-only and are not distribution-cleared.

## Decision

Neither backend reaches the software operating point required before owner
enrollment. On one held-out synthetic corpus of 48 positives and 248
negatives across normal English, hard phonetic, Arabic, mixed, background, and
silence/noise categories:

- BMO MFCC/DTW detected 37/48 positives (77.08%) and falsely activated 15/248
  negatives (6.05%); every false activation was in the hard-phonetic class.
- WakeForge detected 48/48 positives (100%) at its fixed 0.5 threshold but
  falsely activated 248/248 negatives (100%). Its category score ranges
  materially overlap, including silence/noise.

The BMO path remains the active product-owned adapter because it is the safer
architecture and the stronger of these two bounded results, but it is not
selected as an enrollment-ready backend. WakeForge is not integrated and no
owner audio or enrollment is requested. The exact production phrase remains
bare `Jarvis`; `Hey Jarvis` remains non-production. Right Ctrl, PTT, VAD,
Smart Turn, authenticated Core, TTS, barge-in, and the Phase 11 boundary are
unchanged.

## Consequences

The Phase 10 physical owner gate remains paused. A future software-only
iteration must use a larger license-clean, speaker-diverse held-out corpus or
an explicitly approved free backend before one compact owner enrollment
session can be requested. No threshold tuning from this corpus may be used to
claim reliability, and no raw audio is retained.

## Evidence and rollback

Sanitized scalar comparison evidence is recorded in
`docs/phase_reports/evidence/PHASE_10_WAKE_BACKEND_COMPARISON.json`. The
evaluation runner is `scripts/phase_10/compare_wakeforge_backends.py` at
`a7ae0f83f9827ce6e62b10ceee8f9cf8244086e8`. Rollback is documentation-only:
remove the evaluation-only comparison evidence/runner and restore the
ADR-0012 software evidence; no production dependency or runtime artifact is
changed.
