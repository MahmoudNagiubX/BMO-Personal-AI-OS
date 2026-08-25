# ADR-0021: Hey Jarvis Owner-Specific OpenWakeWord Verifier

- Status: accepted for implementation; owner enrollment required
- Date: 2026-08-25
- Supersedes: the active wake-decision portion of ADR-0020; historical measurements remain preserved

## Decision

The Phase 10 wake path uses the pinned official openWakeWord
`hey_jarvis_v0.1.onnx` model as a high-recall candidate, followed by the
upstream-supported openWakeWord custom verifier trained locally from the
owner's bounded enrollment clips. The product-owned adapter invokes the
verifier only after validating a local manifest and the SHA-256 digests of
both the official base model and the derived verifier artifact.

The verifier is stored only at
`%LOCALAPPDATA%/BMO/voice/wake/hey_jarvis_owner_verifier/`. It is never
downloaded, committed, copied into evidence, or accepted from an arbitrary
path. Missing, corrupt, mismatched, symlinked, or incompatible profiles fail
closed. The manifest records the exact phrase, base-model identity, runtime,
artifact digest, validation scalars, owner-local scope, and
`raw_audio_retained=false`.

The enrollment harness uses the installed `openwakeword.train_custom_verifier`
API. Three of five short natural `Hey Jarvis` examples train the profile and
two are reserved for a bounded local sanity check. A bounded non-wake speech
window and ambient window provide negatives. Temporary PCM exists only while
the upstream API requires WAV inputs, is removed on every exit path, and is
never represented in repository evidence. Enrollment does not silently
overwrite an existing valid profile.

The final production sequence is:

```text
ASUS TUF microphone -> 80 ms PCM16 -> official openWakeWord candidate
-> owner-specific openWakeWord verifier -> state-aware gate
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

The owner verifier is local, offline, permanently free to run, and requires
no account, API key, subscription, cloud service, or retained voice data.
