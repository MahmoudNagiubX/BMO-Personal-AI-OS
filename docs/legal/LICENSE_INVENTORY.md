# License Inventory

Update this inventory whenever a dependency, model, voice, dataset, or copied implementation is introduced.

| Component | Pinned version/commit | License | Role | Modified? | Distribution notes | Status |
|---|---|---|---|---:|---|---|
| Personal AI OS original code | Repository release | Apache-2.0 | Product code | Yes | Preserve license and notices | Approved |
| OpenJarvis | v1.0.0 / `e97088f` baseline | Apache-2.0 | Future agent framework through adapter | No initially | Verify package notices at Phase 3 | Approved for spike |
| Leon | No code dependency | MIT | Architectural reference only | No | Record attribution only if code is reused | Reference only |
| Qwen 3.5 4B | To pin in Phase 4 | Verify model card at pull time | Fast local model | No | Record exact Ollama digest and upstream license | Pending Phase 4 |
| Qwen 3.5 9B | To pin in Phase 4 | Verify model card at pull time | Main local model | No | Record exact Ollama digest and upstream license | Pending Phase 4 |
| BGE-M3 | To pin in Phase 4 | Verify model card at pull time | Embeddings | No | Record digest/license | Pending Phase 4 |
| Arabic TTS voice | To pin in Phase 10 | Verify voice/model license | Local TTS | No | Voice-specific obligations required | Pending Phase 10 |
| English TTS voice | To pin in Phase 10 | Verify voice/model license | Local TTS | No | Voice-specific obligations required | Pending Phase 10 |

No non-commercial core dependency may be added without a new ADR.
