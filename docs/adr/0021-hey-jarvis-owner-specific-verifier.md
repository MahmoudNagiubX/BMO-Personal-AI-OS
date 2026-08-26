# ADR-0021: Hey Jarvis Owner-Specific OpenWakeWord Verifier

- Status: accepted for implementation; owner enrollment required
- Date: 2026-08-25
- Supersedes: the active wake-decision portion of ADR-0020; historical measurements remain preserved

## Decision

The Phase 10 wake path uses the pinned official openWakeWord
`hey_jarvis_v0.1.onnx` model with the upstream-supported openWakeWord custom
verifier trained locally from the owner's bounded enrollment clips. The
product-owned adapter validates a local manifest and the SHA-256 digests of
both the official base model and the derived verifier artifact before it
constructs the single upstream detector. There is no redundant application
`WakeCascadeDetector` around that detector.

The verifier is stored only at
`%LOCALAPPDATA%/BMO/voice/wake/hey_jarvis_owner_verifier/`. It is never
downloaded, committed, copied into evidence, or accepted from an arbitrary
path. Missing, corrupt, mismatched, symlinked, or incompatible profiles fail
closed. The manifest records the exact phrase, base-model identity, runtime,
artifact digest, validation scalars, owner-local scope, `production_ready`,
and `raw_audio_retained=false`. It also contains distinct values for the base
candidate invocation threshold, final owner-verifier acceptance threshold,
and temporal/hysteresis policy. The runtime never supplies hidden replacement
thresholds and refuses a provisional or uncalibrated profile.

The enrollment harness uses the pinned OpenWakeWord feature extractor and
`train_verifier_model` primitives through a BMO-owned wrapper
(`scripts.phase_10.owner_verifier_training.train_calibrated_verifier`). The
upstream `train_custom_verifier()` helper silently defaults positive feature extraction
to a `0.5` base score threshold; owner enrollment attempt 2 reached the audio
quality gate but failed at that extractor before producing an artifact. BMO
now supplies the broadly calibrated candidate invocation threshold explicitly,
preflights every positive through the same base model, and records scalar
diagnostics before training. Three of five short natural `Hey Jarvis` examples train the profile and
two are reserved for a bounded local sanity check. A 15-second non-wake speech
window is split into a non-overlapping 10-second training and 5-second holdout
partition; a seven-second ambient window is split into four and three seconds.
The final acceptance threshold is derived only from the reserved positives and
those independent holdouts, never from a fixed value. Temporary PCM exists only while
the upstream API requires WAV inputs, is removed on every exit path, and is
never represented in repository evidence. Enrollment does not silently
overwrite an existing valid profile.

The final production sequence is:

```text
ASUS TUF microphone -> 80 ms PCM16 -> manifest-verified openWakeWord
base model plus owner-specific verifier -> state-aware gate
-> ActivationRouter -> existing VAD/STT/Core/TTS pipeline
```

The faster-whisper model remains the conversational multilingual STT after
wake and is removed from the wake decision. Silero VAD, Pipecat Smart Turn,
pre-roll, one-breath command preservation, Right-Ctrl activation, PTT,
authenticated Core, Phase 8 approvals/audit, Phase 9 authority, follow-up,
and barge-in remain unchanged. No voice path calls Qwen or a tool directly.

## Consequences and acceptance boundary

Generic backend hunting is closed. The prior Whisper cascade, microWakeWord,
bare `Jarvis`, and other measurements remain historical evidence only. No
owner physical session is authorized until the owner-specific profile passes
the bounded owner holdout, synthetic external/hard-negative evaluation,
continuous final-path stream, state-aware playback isolation, resource, and
privacy gates. The owner session remains compact: three to five intended
activations and representative negatives, followed by the combined JARVIS
experience checks. Phase 11 remains `NOT_STARTED`.

Attempt 2 is recorded as an upstream positive-feature-extraction blocker, not
an owner pronunciation or physical wake failure. The owner verifier is local,
offline, permanently free to run, and requires
no account, API key, subscription, cloud service, or retained voice data.
Internal openWakeWord VAD is disabled because its prior measured regression is
historical evidence; Phase 10 uses the existing external state-aware voice
gating instead.
