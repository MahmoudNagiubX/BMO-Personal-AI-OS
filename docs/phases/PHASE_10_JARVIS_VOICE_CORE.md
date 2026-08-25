# Phase 10 - JARVIS Voice Core

## Status

Owner-authorized for implementation on `phase-10/jarvis-voice-core` from the
accepted main base. Phase 10 is the single-device ASUS TUF JARVIS voice core.
Phase 11 room and multi-device voice remains `NOT_STARTED`.

## Goal and boundary

Provide hands-free single-device voice on the ASUS TUF with this normal interaction:

```text
Jarvis -> listening -> local VAD/STT -> authenticated VENOM Core
-> accepted local model gateway -> local TTS -> follow-up listening
-> silence timeout -> wake-word-only idle
```

The normal path does not require push-to-talk. Push-to-talk is a shared
fallback/debug/privacy control. Voice is another Core client modality and does
not bypass identity, conversation, ModelGateway, permissions, approvals,
audit, or the Phase 9 Windows satellite boundary.

This phase does not implement room microphones, multiple speakers, room
presence, ESP32/Pi nodes, far-field room topology, Home Assistant/MQTT,
Flutter, camera/vision work, unrestricted shell, public/LAN inbound voice, or
cloud/paid services.

## Product-owned state machine

The deterministic state machine includes:

`sleeping`, `wake_detected`, `listening`, `speech_detected`, `transcribing`,
`sending`, `waiting_for_response`, `speaking`, `follow_up_listening`,
`interrupted`, `degraded`, `failed`, and the optional `manual_capture` fallback.

It rejects illegal transitions, bounds audio/utterance/queue durations, and
returns to `sleeping` after configurable follow-up silence. Local controls are
limited to stop, cancel spoken output, sleep, repeat, and temporary mute.
Consequential requests continue through Core and exact-owner approval.

## Local pipeline

- Wake word: the exact local `Jarvis` phrase, independent of STT and the
  model. The current product adapter is the BMO-owned `personalized_mfcc_dtw`
  path: NumPy MFCC extraction plus bounded normalized subsequence DTW against
  three or four derived local templates. It loads no pretrained wake or
  embedding weights. The microWakeWord, Sherpa KWS, Vosk, PocketSphinx, and
  local-wake neural candidates are preserved as historical evidence rather
  than silently reused.
- `scripts/phase_10/train_jarvis_micro_wake_word.py` invokes the pinned
  Apache-2.0 microWakeWord trainer with synthetic local Piper/Sherpa speech,
  deterministic augmentation, and no public or mixed-license audio dataset.
  Temporary WAVs, features, and checkpoints are deleted before the command
  returns. The committed manifest records the upstream source commit and
  artifact digest; the model remains outside Git until separately approved.
- openWakeWord remains a historical/reference benchmark only. Picovoice
  Porcupine, AccessKeys, subscriptions, trials, and paid wake-word services
  are rejected. The local-wake project is used only as an MIT implementation
  reference because its bundled neural embedding artifact lacks sufficient
  model-specific provenance/license. Continuous heavy Whisper is not an idle
  wake-word backend.
- VAD: Silero VAD or a measured compatible local replacement.
- STT: local multilingual faster-whisper, with `medium` as the benchmark
  baseline.
- TTS: sherpa-onnx with `vits-piper-ar_JO-kareem-medium` as the Arabic
  baseline, plus a bounded local English Piper/VITS comparison.
- Coordination: Pipecat Smart Turn v3.x and Silero VAD behind product-owned
  interfaces; framework types do not leak through domain contracts. A bounded
  timeout remains the deterministic fallback.
- Capture and playback: local Windows user-session devices only.

Exact versions, artifacts, licenses, hashes, and measured resource use are
recorded in the Phase 10 evidence and license inventory.

The rejected wake candidates remain historical evidence in their dedicated
reports and manifests. The active software path is implemented in
`src/personal_ai_os/voice/mfcc.py` and
`PersonalizedMfccDtwWakeWordDetector`; the non-owner viability benchmark is
`scripts/phase_10/benchmark_personalized_mfcc_wakeword.py`. It records scalar
metrics and never writes PCM. Enrollment is one bounded local command that
persists only derived MFCC templates with integrity metadata. Exact `Jarvis`,
double-tap Right Ctrl, and PTT all enter the same pipeline. A bounded
in-memory pre-roll preserves words following activation; Smart Turn improves
endpointing; safe phrase/sentence TTS chunks are ordered and cancellable for
real barge-in. The authenticated VENOM Core transport is still the only
assistant path, and Qwen is never called directly by voice.

## Privacy and degraded behavior

Idle wake-word audio is bounded and in memory only. Raw audio is not stored in
Git, logs, audit, the database, or VENOM. Temporary audio files, if a local
backend requires them, are private, bounded, and deleted on every success,
failure, cancellation, interruption, and shutdown path.

No speech produces no STT/model request. Missing microphone, wake-word, STT,
TTS, playback, Core, or model gateway produces an explicit degraded state or
text-preserving fallback; it never creates a local authority bypass.
The physical runner captures a short ambient baseline and derives bounded,
device-relative RMS/peak thresholds. Measurable signal above that baseline is
sent to the active MFCC detector; only signal below the calibrated floor is
`NO_AUDIO`, while a recognized-input failure is a `WAKE_MISS`.

## Acceptance boundary

Acceptance requires one short natural-use ASUS TUF session with only three to
five intended bare-`Jarvis` activations and compact representative English,
Arabic, background, and playback non-wake cases. It must also prove the shared
Right-Ctrl activation route, a one-utterance wake-plus-command pre-roll turn,
Smart Turn across a short natural pause, Arabic/English/mixed speech, follow-up
turns without repeating `Jarvis`, silence timeout, non-wake/no-speech
suppression, barge-in, interruption recovery, local session controls, PTT
fallback, no-retention cleanup, degraded modes, latency, resource/thermal
stability, and repeated turns. The prior 20-round owner calibration is
historical evidence only; automated/synthetic benchmarks provide development
coverage. Phase 9, Qwen 4B, and optional Qwen 9B regressions must remain intact.
Phase 11 remains `NOT_STARTED`.

See ADR-0010 for the accepted Phase 10/11 architecture boundary.
