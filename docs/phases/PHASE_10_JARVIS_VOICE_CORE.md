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

- Wake word: local `Jarvis`, independent of STT and the model.
- VAD: Silero VAD or a measured compatible local replacement.
- STT: local multilingual faster-whisper, with `medium` as the benchmark
  baseline.
- TTS: sherpa-onnx with `vits-piper-ar_JO-kareem-medium` as the Arabic
  baseline, plus a bounded local English Piper/VITS comparison.
- Coordination: Pipecat behind product-owned interfaces; framework types do
  not leak through domain contracts.
- Capture and playback: local Windows user-session devices only.

Exact versions, artifacts, licenses, hashes, and measured resource use are
recorded in the Phase 10 evidence and license inventory.

## Privacy and degraded behavior

Idle wake-word audio is bounded and in memory only. Raw audio is not stored in
Git, logs, audit, the database, or VENOM. Temporary audio files, if a local
backend requires them, are private, bounded, and deleted on every success,
failure, cancellation, interruption, and shutdown path.

No speech produces no STT/model request. Missing microphone, wake-word, STT,
TTS, playback, Core, or model gateway produces an explicit degraded state or
text-preserving fallback; it never creates a local authority bypass.

## Acceptance boundary

Acceptance requires real ASUS TUF evidence for wake-word-only idle, Arabic,
English, mixed speech, follow-up turns without repeating `Jarvis`, silence
timeout, non-wake/no-speech suppression, barge-in, interruption recovery,
local session controls, PTT fallback, no-retention cleanup, degraded modes,
latency, resource/thermal stability, and repeated turns. Phase 9, Qwen 4B,
and optional Qwen 9B regressions must remain intact. Phase 11 remains
`NOT_STARTED`.

See ADR-0010 for the accepted Phase 10/11 architecture boundary.
