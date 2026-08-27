# BMO / JARVIS Personal AI OS — Current Live System Map

This document defines the live architecture, subsystem topology, data flow, voice state machine, and barge-in path for the BMO / JARVIS Personal AI OS as accepted at Phase 10 closeout.

---

## 1. End-to-End System Topology

```text
+-----------------------------------------------------------------------------------------+
|                                    ASUS TUF (Heavy Compute)                             |
|                                                                                         |
|  [ Microphones / Hotkey ] ---> [ SoundDevice Capture ] ---> [ Silero VAD ]              |
|                                                                    |                    |
|                                                      [ Speech Candidate (0.48-1.8s) ]   |
|                                                                    |                    |
|                                                     [ Faster-Whisper base.en CPU int8 ] |
|                                                                    |                    |
|                                                         [ Exact "Hey Jarvis" ]          |
|                                                                    |                    |
|  [ Double Right-Ctrl / PTT ] -----------------------------> [ Activation ]              |
|                                                                    |                    |
|                                                         [ JarvisConversationLoop ]      |
|                                                                    |                    |
|  [ Speech Audio ] ------------> [ Faster-Whisper medium STT (CUDA fp16) ]               |
|                                                                    |                    |
|                                                          [ Finalized Utterance ]        |
|                                                                    |                    |
|                                                   [ Authenticated Reverse Tunnel ]      |
|                                                   (ASUS 127.0.0.1:18000 -> VENOM :8000) |
+--------------------------------------------------------------------+--------------------+
                                                                     |
                                                                     v
+-----------------------------------------------------------------------------------------+
|                                   LENOVO / VENOM (Control Plane)                        |
|                                                                                         |
|                         [ bmo-core FastAPI Service (127.0.0.1:8000) ]                   |
|                                                                                         |
|    +-------------------------+-------------------------+---------------------------+    |
|    | Device Identity & Auth  |  Conversation Sessions  | Tool Permissions & Audit  |    |
|    | (TUF Enrolled / Token)  |  (Context & History)    | (Allowlists & Approvals)  |    |
|    +-------------------------+-------------------------+---------------------------+    |
|                                           |                                             |
|                             [ PostgreSQL 127.0.0.1:5432 ]                               |
|                                           |                                             |
|                             [ ModelGateway Router ]                                     |
+-------------------------------------------+---------------------------------------------+
                                            |
                         (Authenticated Reverse SSH Tunnel)
                         (VENOM 127.0.0.1:11434 -> ASUS :11434)
                                            |
                                            v
+-----------------------------------------------------------------------------------------+
|                                    ASUS TUF (Model Node)                                |
|                                                                                         |
|               [ Ollama v0.32.5 Conservative CUDA (127.0.0.1:11434) ]                    |
|               - Primary LLM: Qwen 3.5 4B (Instruct / Orchestration)                     |
|               - Embeddings: BGE-M3 (1024-dim)                                           |
|               [ Optional llama.cpp (127.0.0.1:11435): Qwen 3.5 9B ]                     |
+-------------------------------------------+---------------------------------------------+
                                            |
                                  [ Response Stream ]
                                            |
                                            v
+-----------------------------------------------------------------------------------------+
|                                 ASUS TUF (Presentation & Action)                        |
|                                                                                         |
|    +--------------------------------------+  +-------------------------------------+    |
|    |        Local TTS & Playback          |  |          Windows Satellite          |    |
|    | - sherpa-onnx VITS Piper (en_US/ar_JO)|  | - Outbound Authenticated WS/HTTP    |    |
|    | - Phrase-level cancellable streaming |  | - Strict allowlisted typed actions  |    |
|    | - SoundDevice audio playback         |  |   (app_open, project_open, volume)  |    |
|    +--------------------------------------+  +-------------------------------------+    |
|                       |                                                                 |
|            [ Cancellable Output ]                                                       |
|                       |                                                                 |
|            [ Real Barge-in Support ] <--- [ Interruption Frame Capture ]                |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Voice Coordinator State Machine

The product-owned voice state machine (`JarvisConversationLoop` + `JarvisVoicePipeline`) transitions strictly through verified states with zero partial Core submissions and bounded in-memory audio buffers:

```text
                              +---------------+
                              |   SLEEPING    | <---------------+
                              +---------------+                 |
                                |           |                   |
               "Hey Jarvis" wake|           | Right-Ctrl / PTT  | (Silence Timeout
                                v           v   activation      |  or Sleep Intent)
                         +---------------------+                |
                         |      LISTENING      |                |
                         +---------------------+                |
                                |                               |
                    Speech Start| (VAD Detection)               |
                                v                               |
                         +---------------------+                |
                         |   SPEECH_DETECTED   |                |
                         +---------------------+                |
                                |                               |
                      Speech End| (Smart Turn Endpointing)      |
                                v                               |
                         +---------------------+                |
                         |     TRANSCRIBING    |                |
                         +---------------------+                |
                                |                               |
                      STT Ready | (Multilingual faster-whisper) |
                                v                               |
                         +---------------------+                |
                         |       SENDING       |                |
                         +---------------------+                |
                                |                               |
                    Core Request| (Authenticated HTTP/SSE)      |
                                v                               |
                         +---------------------+                |
                         | WAITING_FOR_RESPONSE|                |
                         +---------------------+                |
                                |                               |
                  Response Ready| (First Phrase Synthesized)    |
                                v                               |
                         +---------------------+                |
         +-------------> |      SPEAKING       |                |
         |               +---------------------+                |
         |                      |          |                    |
         |         Playback Done|          | Interruption       |
         |                      v          v (Speech Detected)  |
         |             +--------------+  +-------------+        |
         |             |  FOLLOW_UP_  |  | INTERRUPTED |        |
         |             |  LISTENING   |  +-------------+        |
         |             +--------------+         |               |
         |                      |               | (Cancel TTS & |
         |      Follow-up Speech|               |  Keep Frames) |
         |                      +---------------+---------------+
         |                              |
         +------------------------------+
```

---

## 3. Real Barge-In & Interruption Path

1. **Active Playback**: JARVIS speaks response audio in phrase chunks via `CancellableTtsStream` through `SoundDeviceBackend`.
2. **Concurrent Microphone Streaming**: Live capture frames (80 ms, 16 kHz mono PCM16) continue streaming into `JarvisConversationLoop.on_frame()`.
3. **Echo Reference Guard**: Frames matching the active playback reference are ignored (`playback_echo_frames_ignored`).
4. **Interruption Detection**: Novel user speech exceeding the calibrated noise floor triggers `VoiceEvent.INTERRUPTION`.
5. **Instant Cancellation**: Active playback is halted immediately (`playback.stop()`), queued audio is discarded, and coordinator cancellation latency is measured ($p_{50} \le 300\text{ ms}$, $p_{95} \le 450\text{ ms}$).
6. **Pre-Roll Preservation**: The initial 160 ms of the interrupting utterance is preserved in memory.
7. **Same Core Session**: STT transcribes the new utterance and submits it to the same authenticated Core conversation session without requiring a wake phrase.

---

## 4. Locked System Boundaries

1. **No Direct Model/Tool Bypass**: All user speech must pass through authenticated Core. Audio devices never invoke tools or Ollama directly.
2. **Zero Audio Persistence**: Microphones capture strictly in bounded memory buffers. Raw audio is never written to disk, database, logs, or VENOM.
3. **Loopback-Only Bindings**:
   - VENOM Core: `127.0.0.1:8000`
   - VENOM PostgreSQL: `127.0.0.1:5432`
   - ASUS Ollama: `127.0.0.1:11434`
   - ASUS llama.cpp: `127.0.0.1:11435`
4. **Single-Device Phase Boundary**: Voice capture, wake word, STT, and TTS remain on ASUS TUF. Phase 11 multi-device room voice is `NOT_STARTED`.
5. **Exactly-Once Invariant**: Exactly one finalized utterance = exactly one STT finalization = exactly one authenticated Core submission.
