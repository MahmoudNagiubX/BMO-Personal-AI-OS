# License Inventory

Update this inventory whenever a dependency, model, voice, dataset, or copied implementation is introduced.

| Component | Pinned version/commit | License | Role | Modified? | Distribution notes | Status |
|---|---|---|---|---:|---|---|
| Personal AI OS original code | Repository release | Apache-2.0 | Product code | Yes | Preserve license and notices | Approved |
| OpenJarvis | `OpenJarvis==1.0.0`; v1.0.0 / `e97088f199cf86ea5f78de921772357d1f0d2cec` provenance | Apache-2.0 | Compatibility spike through product-owned adapter | No | Official PyPI registry; wheel SHA-256 `5d56bf50e556f2eb6612cb49e844557e10a083094e527cb59f03fd257f3dc7d4`; sdist SHA-256 `1673d5160a5574bee789d4f0528239fc85e5f45ba0b5093c1c34024183ddcb44`; no external analytics traffic; no model loaded | Phase 3 merged |
| Leon | No code dependency | MIT | Architectural reference only | No | Record attribution only if code is reused | Reference only |
| Qwen 3.5 4B | Ollama `qwen3.5:4b`; digest `sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd` | Apache-2.0 | Initial primary local generation, conversation, orchestration, vision, structured output, and typed tool-call data | No | Official upstream/model card: `https://huggingface.co/Qwen/Qwen3.5-4B`; locally verified Ollama packaging digest; no cloud fallback | Accepted Phase 4 model |
| Qwen3.5-9B Heretic v2 Q4_K_M | Owner-approved local artifact; SHA-256 `8d463c63e2c8759ad263cba59f1fa7a0be9a7cacb59b0fd0a787b7daa31597ad` | Upstream/derivative terms require legal review | Optional Phase 8.5 advanced local-only generation | No | Not official Qwen packaging; artifact remains outside Git and is never downloaded by repository automation; distribution is not authorized until provenance/license review | Admission evidence only |
| BGE-M3 | Ollama `bge-m3:567m`; digest `sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab` | MIT | Local multilingual embeddings, 1024 dimensions | No | Official upstream/model card: `https://huggingface.co/BAAI/bge-m3`; locally verified Ollama packaging digest; no cloud fallback | Accepted Phase 4 model |
| websockets | `15.0.1` | BSD-3-Clause | Authenticated Phase 7 text client and Phase 9 outbound Windows satellite transport | No | PyPI package resolved in `uv.lock`; no external telemetry | Phase 7/9 repository dependency |
| psutil | `7.2.2` | BSD-3-Clause | Bounded local Windows satellite CPU, memory, storage, network, and battery telemetry | No | PyPI package resolved in `uv.lock`; telemetry remains local and excludes identity/serial data | Phase 9 repository dependency |
| Arabic TTS voice | To pin in Phase 10 | Verify voice/model license | Local TTS | No | Voice-specific obligations required | Pending Phase 10 |
| English TTS voice | To pin in Phase 10 | Verify voice/model license | Local TTS | No | Voice-specific obligations required | Pending Phase 10 |

No non-commercial core dependency may be added without a new ADR.
