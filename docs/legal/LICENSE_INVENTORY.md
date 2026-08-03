# License Inventory

Update this inventory whenever a dependency, model, voice, dataset, or copied implementation is introduced.

| Component | Pinned version/commit | License | Role | Modified? | Distribution notes | Status |
|---|---|---|---|---:|---|---|
| Personal AI OS original code | Repository release | Apache-2.0 | Product code | Yes | Preserve license and notices | Approved |
| OpenJarvis | `OpenJarvis==1.0.0`; v1.0.0 / `e97088f199cf86ea5f78de921772357d1f0d2cec` provenance | Apache-2.0 | Compatibility spike through product-owned adapter | No | Official PyPI registry; wheel SHA-256 `5d56bf50e556f2eb6612cb49e844557e10a083094e527cb59f03fd257f3dc7d4`; sdist SHA-256 `1673d5160a5574bee789d4f0528239fc85e5f45ba0b5093c1c34024183ddcb44`; no external analytics traffic; no model loaded | Local validation and latest-head GitHub CI complete; owner merge pending |
| Leon | No code dependency | MIT | Architectural reference only | No | Record attribution only if code is reused | Reference only |
| Qwen 3.5 4B | To pin in Phase 4 | Verify model card at pull time | Fast local model | No | Record exact Ollama digest and upstream license | Pending Phase 4 |
| Qwen 3.5 9B | To pin in Phase 4 | Verify model card at pull time | Main local model | No | Record exact Ollama digest and upstream license | Pending Phase 4 |
| BGE-M3 | To pin in Phase 4 | Verify model card at pull time | Embeddings | No | Record digest/license | Pending Phase 4 |
| Arabic TTS voice | To pin in Phase 10 | Verify voice/model license | Local TTS | No | Voice-specific obligations required | Pending Phase 10 |
| English TTS voice | To pin in Phase 10 | Verify voice/model license | Local TTS | No | Voice-specific obligations required | Pending Phase 10 |

No non-commercial core dependency may be added without a new ADR.
