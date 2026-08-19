# Third-Party Notices

No third-party source code is copied into the Phase 0 repository bootstrap.

The project plans to integrate external components as dependencies or external services. Their exact versions, licenses, notices, and modification status must be recorded in `LICENSE_INVENTORY.md` before distribution.

Architectural references do not imply code inclusion. If code is copied or modified later, add the required attribution and license text in the same change.

Phase 8.5 records the externally installed, unmodified llama.cpp b10502
runtime as a pinned local tool. Its executable and the owner-approved derived
Qwen3.5-9B Heretic v2 GGUF remain outside Git; the exact hashes and local-only
distribution boundary are recorded in `infrastructure/tuf/model_manifest.json`
and ADR-0009. No llama.cpp source is copied into this repository.
