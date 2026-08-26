# Phase 10 - JARVIS Voice Core

## Status

Owner-authorized for implementation on `phase-10/jarvis-voice-core` from the
accepted main base. Phase 10 is the single-device ASUS TUF JARVIS voice core.
Phase 11 room and multi-device voice remains `NOT_STARTED`.

## Goal and boundary

Provide hands-free single-device voice on the ASUS TUF with this normal interaction:

```text
Hey Jarvis -> listening -> local VAD/STT -> authenticated VENOM Core
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

- Wake word: the exact local `Hey Jarvis` phrase, independent of
  conversational STT and the model. The active product-owned adapter is the
  in-process Rhasspy `pyopen-wakeword==1.1.0` streaming flow using the built-in
  `Model.HEY_JARVIS` model. It keeps persistent feature/model state, splits
  each BMO 80 ms frame into eight exact 10 ms PCM16 chunks, and uses the mature
  `threshold=0.5`, `trigger_level=1`, `refractory=2.0s` policy. The compact
  physical probe remains pending; no owner enrollment is required.
- The prior bare-`Jarvis`, microWakeWord, Sherpa KWS, Vosk, PocketSphinx,
  personalized MFCC/DTW, WakeForge, and other candidates are historical
  evidence only. Their runnable experiment paths were removed after the
  backend reselection audit; the historical reports and ADRs remain.
- Picovoice Porcupine, AccessKeys, subscriptions, trials, and paid wake-word
  services are rejected. Continuous heavy Whisper is not an idle wake-word
  backend. The official model identity, revision, checksum, and separate
  engine/model licenses are pinned in ADR-0018, ADR-0019, ADR-0020, and the
  final comparison evidence.
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

The rejected and superseded wake candidates remain historical evidence in
their dedicated reports and manifests. The active wake adapter is
`RhasspyHeyJarvisDetector`, using the built-in package model and its exact
installed SHA-256 recorded in ADR-0022 and the Rhasspy manifest. The
Apache-2.0 `wyoming-openwakeword` trigger/refractory behavior is a reference
only; no Wyoming networking is included. The old owner-verifier and Whisper
wake paths remain historical and are not active; faster-whisper remains the
conversational STT after wake. The wake-only diagnostic is
`scripts/phase_10/run_hey_jarvis_reference_probe.ps1`; it records only scalar
metrics and never commits PCM. The owner-free scalar benchmark is
`scripts/phase_10/benchmark_rhasspy_hey_jarvis.py`; positive recall is reported
only when local WAV inputs are explicitly supplied. The double-tap Right Ctrl activation and PTT
all enter the same pipeline. A bounded in-memory pre-roll preserves words
following activation; Smart Turn improves endpointing; safe phrase/sentence
TTS chunks are ordered and cancellable for real barge-in. The authenticated
VENOM Core transport is still the only assistant path, and Qwen is never
called directly by voice.

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
sent to the active manifest-verified Hey Jarvis detector; only signal below the calibrated floor is
`NO_AUDIO`, while a recognized-input failure is a `WAKE_MISS`.

## Backend reselection software gate

The official current ESPHome microWakeWord v2 `Hey Jarvis` artifact was
verified from `esphome/micro-wake-word-models` main commit
`05b65922cc433c9df13e98e32a7fe520758c837e`, with artifact SHA-256
`21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77`. Its
independent held-out result was 217/504 recall (43.06%) and 262/7,268 raw
false activations (3.60%). The microWakeWord path was rejected before a long
continuous stream was justified.

The incumbent openWakeWord cascade was freshly measured at 489/504 recall
(97.02%), 75/7,268 raw false activations (1.03%), and one false wake in a
five-hour continuous stream (0.2 FAPH). It therefore misses the 98% / 0.25%
/ 0.1 FAPH software gate. Raw acoustic FAR and production-reachable FAR are
kept distinct. Those results remain historical evidence. ADR-0022 now replaces
that incumbent with the direct Rhasspy streaming path; no owner physical
session is authorized until its compact probe is ready. See
`evidence/PHASE_10_WAKE_BACKEND_RESELECTION.json`,
`evidence/PHASE_10_RHASSPY_WAKE_CORE.json`, and ADR-0020/ADR-0022.

## Acceptance boundary

Acceptance requires the migration software gate first, followed by one short
natural-use ASUS TUF session with only three to five intended `Hey Jarvis`
activations and compact representative English,
Arabic, background, and playback non-wake cases. It must also prove the shared
Right-Ctrl activation route, a one-utterance wake-plus-command pre-roll turn,
Smart Turn across a short natural pause, Arabic/English/mixed speech, follow-up
turns without repeating the wake phrase, silence timeout, non-wake/no-speech
suppression, barge-in, interruption recovery, local session controls, PTT
fallback, no-retention cleanup, degraded modes, latency, resource/thermal
stability, and repeated turns. The prior 20-round owner calibration is
historical evidence only; automated/synthetic benchmarks provide development
coverage. Until the Rhasspy direct path passes its compact owner probe, the
physical gate is blocked and no owner session is requested. Phase 9, Qwen
4B, and optional Qwen 9B regressions must remain intact.
Phase 11 remains `NOT_STARTED`.

See ADR-0010 for the accepted Phase 10/11 architecture boundary, ADR-0018
through ADR-0021 for preserved historical evidence, and ADR-0022 for the
active Rhasspy streaming wake implementation.
