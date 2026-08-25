# Third-Party Notices

No third-party source code is copied into the Phase 0 repository bootstrap.

The project plans to integrate external components as dependencies or external services. Their exact versions, licenses, notices, and modification status must be recorded in `LICENSE_INVENTORY.md` before distribution.

Phase 10 local voice artifacts are not copied into this repository. The pinned
Python packages are used behind product-owned adapters. The official
openWakeWord `hey_jarvis_v0.1.onnx` model is the current owner-local migration
candidate; its exact `v0.5.1` provenance, Apache-2.0 license, and SHA-256 are
recorded in `LICENSE_INVENTORY.md` and ADR-0018. Its software gate is not yet
passed, so it is not physical acceptance evidence or a release claim. The
attempted derived bare `Jarvis` openWakeWord candidate and microWakeWord
candidate remain historical owner-local artifacts outside Git. No
Picovoice/Porcupine dependency or credential is used. Vosk remains historical
evidence and is not silently substituted for this owner-authorized migration.
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
