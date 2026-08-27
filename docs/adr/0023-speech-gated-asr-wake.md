# ADR-0023 — Speech-gated ASR for the Hey Jarvis wake path

- Status: Accepted for Phase 10 implementation
- Date: 2026-08-26
- Supersedes: the active wake implementation portions of ADR-0022

## Context

The owner-rejected Rhasspy physical probe is historical evidence and must not
be repeated or tuned. The active product needs an exact `Hey Jarvis` wake
phrase without a KWS candidate, owner enrollment, paid service, or retained
audio. The accepted Phase 10 experience remains a single-device ASUS TUF
voice core; room and multi-device voice remain Phase 11.

## Decision

Use the product-owned `SpeechGatedHeyJarvisDetector` as the only active wake
detector. Its bounded pipeline is:

```text
Silero VAD -> bounded in-memory speech candidate -> faster-whisper wake ASR
-> exact Hey Jarvis prefix -> BMO activation
```

Silero VAD is a speech gate only. It never makes a wake decision. The
short-phrase `faster-whisper` recognizer owns the decision through the existing
`WhisperWakePhraseVerifier`, which normalizes punctuation/case and accepts only
the exact two-token prefix `Hey Jarvis`, with optional following command text.
Bare `Jarvis`, near matches, and phrases where the words occur later are
rejected. No openWakeWord, Rhasspy, microWakeWord, Vosk, KWS, owner verifier,
or enrollment path is active.

The production deployment contract is the official
`Systran/faster-whisper-base.en` revision
`3d3d5dee26484f91867d81cb899cfcf72b96be6c`, MIT licensed, using CPU `int8`,
beam size 1, and no hotwords. Tiny CPU, base CUDA, and hotword variants are
benchmark comparisons only. The selected model is loaded independently from
the conversational multilingual STT model.

The candidate is bounded to 16 kHz mono PCM16, a 1.8 second maximum window,
0.64 second VAD window, 0.32 second minimum/initial verification window,
0.16 second retry cadence, four maximum ASR attempts, and 0.48 second
speech-end silence. Audio remains process memory and is cleared after
acceptance, rejection, reset, interruption, or failure.

Wake detection is armed only in the pipeline's `SLEEPING` state. Right-Ctrl
double-tap and push-to-talk continue through the same activation/session path;
they do not create an alternate model or authority path. The existing bounded
pre-roll preserves a command spoken immediately after the wake phrase.

## Validation and acceptance boundary

The owner-free benchmark uses seeded synthetic local Piper/Sherpa audio and
records scalar recall, false activations, latency, CPU, and memory only. A
selected implementation must meet at least 98% recall and at most 0.25% false
activation rate on the bounded corpus before the owner probe is requested.
The current bounded streaming diagnostic is below that gate at 5/6 positive
detections (83.33% recall) and 1/21 negative false activations (4.76% FAR),
including one hard-phonetic false activation; this is diagnostic evidence, not
an acceptance result, and the owner probe remains blocked.
The exact-head hosted CI result is an external governance check and is not
self-attested in the committed evidence.

The final physical probe is intentionally compact: three intended natural
`Hey Jarvis` activations (normal, owner-accented, and moderate distance) plus
five representative non-wake cases. It is not a 20-round owner calibration.
The probe remains pending until software evidence is complete. Physical
acceptance must still cover the shared Right-Ctrl route, one-utterance
pre-roll, Smart Turn, multilingual conversation, follow-up, barge-in,
silence, PTT, resource/thermal behavior, Phase 9 regression, and privacy.

## Consequences

The wake path has a larger per-candidate ASR cost than a KWS detector, so the
VAD gate and strict candidate bounds are mandatory. It avoids a misleading
classifier threshold and keeps all language acceptance in one exact-prefix
verifier. It also keeps model/runtime failure explicit and fail-closed without
falling back to direct Core, model, or tool execution.

The rejected Rhasspy, openWakeWord, microWakeWord, Vosk, and owner-verifier
experiments remain preserved as historical evidence. No raw owner audio,
credentials, transcripts, or model artifacts are committed. Phase 11 remains
`NOT_STARTED`.
