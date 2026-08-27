# ADR-0016: State-Aware Wake Arming and Assistant Self-Playback Isolation

**Status:** Accepted — Software operating point passed; authorized for single compact physical owner acceptance gate  
**Date:** 2026-08-25  
**Supersedes:** Resolves the acoustic playback blocker in ADR-0015  
**Owner:** Mahmoud

## Context

ADR-0015 established that the local exact `Jarvis` wake verifier using `faster-whisper-base.en` on CUDA float16 achieves high acoustic recall (144/150, 96.0%) and zero false activations across 975 external negative samples (0.0% FAR across normal English, hard phonetics, Arabic, mixed speech, background conversation, silence/noise, media playback, and fan/keyboard noise). However, 45 false activations were recorded exclusively when acoustic verification was tested against synthetic assistant TTS output containing the word "Jarvis".

In a state-unaware isolated recognizer test, synthesized assistant speech containing "Jarvis" is acoustically valid speech. However, in the real Personal AI OS runtime, `JarvisVoicePipeline` and its underlying state machine (`VoiceStateMachine`) possess authoritative awareness of the voice lifecycle state (`SLEEPING`, `LISTENING`, `SPEAKING`, `FOLLOW_UP_LISTENING`, `INTERRUPTED`, `DEGRADED`).

Wake inference is meaningful and necessary *only* when the system is `SLEEPING`. When the system is `SPEAKING` (emitting assistant TTS) or in `FOLLOW_UP_LISTENING` (expecting user conversational speech without wake words), the pipeline must disarm wake detection. Furthermore, audio pre-roll must accumulate frames strictly during `SLEEPING` so that playback audio never pollutes the speech recognizer buffer for subsequent turns.

Additionally, Linux CI experienced a Mypy portability failure due to direct references to `os.add_dll_directory` in `personal_ai_os.voice.adapters`, which is a Windows-only CPython attribute absent from Linux typeshed.

## Decision

1. **Linux CI Portability Recovery:** Refactored native Windows library registration in `src/personal_ai_os/voice/adapters.py` into a platform-safe helper (`_register_dll_directory`) using `getattr(os, "add_dll_directory", None)`. Verified clean Mypy passes on both Windows and Linux target platforms (`uv run mypy --platform linux` and `uv run mypy`).
2. **State-Aware Wake Arming:** Hardened `JarvisVoicePipeline.on_capture_frame` and `on_wake_frame` in `src/personal_ai_os/voice/pipeline.py` to assert `self.state is VoiceState.SLEEPING` before performing candidate or verifier wake inference. Outside `SLEEPING` (such as during `SPEAKING` and `FOLLOW_UP_LISTENING`), incoming capture frames return `False` immediately without consuming CPU or GPU inference cycles. The underlying acoustic verifier recognizes "Jarvis" in assistant playback when tested in isolation, but runtime architectural gating prevents audio playback from reaching the verifier during active speech emission or interactive follow-up turns. This is state-aware architectural isolation, not a claim that the acoustic verifier itself possesses zero self-playback FAR.
3. **Pre-Roll Isolation:** Frame accumulation in `self.pre_roll` is restricted strictly to `VoiceState.SLEEPING`. Assistant playback frames during `SPEAKING` and `FOLLOW_UP_LISTENING` are completely excluded from pre-roll buffers.
4. **Lifecycle Detector and Buffer Resets:** Wired `_reset_detector()` and buffer cleanups into `sleep()`, silence timeout transitions, `barge_in()`, `start_keyboard_capture()`, `start_manual_capture()`, and `process_utterance()` failure and completion paths.
5. **Stateful Integration Validation:** Implemented `scripts/phase_10/benchmark_stateful_wake_isolation.py` and comprehensive unit tests in `tests/unit/voice/test_pipeline.py`. Evaluated the end-to-end production pipeline across all 150 positive samples and 1,075 negative samples (including the 100 assistant TTS playback samples) on the ASUS TUF compute plane (NVIDIA GeForce RTX 4050 Laptop GPU):
   - **Sleeping Positives:** 150/150 detections (100.0% recall, meeting >=95%).
   - **Sleeping External Negatives:** 0/975 false activations (0.0% FAR, meeting <=0.5%).
   - **Speaking Assistant Playback:** 0/100 verifier invocations, 0/100 wake transitions, 0/100 duplicate Core submissions (100% isolated).
   - **Follow-Up Assistant Playback:** 0/100 verifier invocations, 0/100 wake transitions, 100/100 owner follow-up turns passed cleanly.
   - **Stale-Tail & Immediate-Sleep Simulations:** 0 tail activations, 20/20 subsequent wakes passed cleanly.
   - **Barge-In Simulation:** 20/20 barge-in interruptions cleanly stopped playback and transitioned to `LISTENING`.
   - **Single-Utterance Pre-Roll Simulation:** 20/20 single-utterance commands ("Jarvis <command>") preserved command speech via pre-roll.
   - **Production-Reachable FAR:** 0.0% (0 / 1,075).
   - **Performance:** Warm latency 49.158 ms p50 / 62.701 ms p95; GPU memory 1.74 GB VRAM at 62 C on NVIDIA GeForce RTX 4050 Laptop GPU.

This resolves the self-playback blocker, satisfies the software acceptance gate, and authorizes the single compact physical owner acceptance session.

Phase 11 remains `NOT_STARTED`.

## Consequences and next gate

The dual activation model (exact bare `Jarvis` and double-Right-Ctrl) operates through the unified `JarvisVoicePipeline`. The single owner physical acceptance session on the ASUS TUF compute plane can proceed using `scripts/phase_10/run_local_acceptance.ps1`.

## Evidence and rollback

Scalar evidence is committed to `docs/phase_reports/evidence/PHASE_10_STATEFUL_WAKE_ISOLATION.json` and validated by `scripts/phase_10/validate_evidence.py`. Both the raw acoustic verifier metrics (96% recall, 4.19% acoustic FAR caused by assistant playback) and the production state-gated metrics (100% recall, 0.0% production FAR, 0 assistant playback wake transitions) are preserved.

Rollback is documentation and code revision to commit `e9de3ead8b1deccf67e135ab0f84e02ee805ce30`. No owner audio or external cloud APIs are used.
