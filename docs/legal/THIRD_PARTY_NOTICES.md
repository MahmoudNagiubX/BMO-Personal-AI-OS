# Third-Party Notices

No third-party source code is copied into the Phase 0 repository bootstrap.

The project plans to integrate external components as dependencies or external services. Their exact versions, licenses, notices, and modification status must be recorded in `LICENSE_INVENTORY.md` before distribution.

Phase 10 local voice artifacts are not copied into this repository. The pinned
Python packages are used behind product-owned adapters. The official
openWakeWord `hey_jarvis_v0.1.onnx` model is the pinned high-recall candidate
for the owner-specific local custom verifier. The derived verifier is owner
local, is not distributed, and is not committed. The historical faster-whisper
wake verifier is not active; faster-whisper remains conversational STT.
candidate; its exact `v0.5.1` provenance, CC-BY-NC-SA-4.0 pretrained-model
license, and SHA-256 are recorded in `LICENSE_INVENTORY.md` and ADR-0018. Its software gate is not yet
passed, so it is not physical acceptance evidence or a release claim. The
attempted derived bare `Jarvis` openWakeWord candidate and microWakeWord
candidate remain historical owner-local artifacts outside Git. No
Picovoice/Porcupine dependency or credential is used. Vosk remains historical
evidence and is not silently substituted for this owner-authorized migration.
The official ESPHome microWakeWord v2 `hey_jarvis.tflite` artifact was also
freshly evaluated from main commit `05b65922cc433c9df13e98e32a7fe520758c837e`
with SHA-256 `21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77`.
The collection is Apache-2.0, but artifact-specific terms are not declared;
the candidate failed the software gate and is not integrated or distributed.
Its temporary `pymicro-wakeword` runtime was removed after the comparison.
The sherpa-onnx Arabic `vits-piper-ar_JO-kareem-medium` and English
`vits-piper-en_US-lessac-medium` artifacts remain outside Git and retain their
upstream model-card obligations. See `LICENSE_INVENTORY.md` for exact pins and
the physical-admission status.

Architectural references do not imply code inclusion. If code is copied or modified later, add the required attribution and license text in the same change.

Phase 8.5 records the externally installed, unmodified llama.cpp b10502
runtime as a pinned local tool. Its executable and the owner-approved derived
Qwen3.5-9B Heretic v2 GGUF remain outside Git; the exact hashes and local-only
distribution boundary are recorded in `infrastructure/tuf/model_manifest.json`
and ADR-0009. No llama.cpp source is copied into this repository.
