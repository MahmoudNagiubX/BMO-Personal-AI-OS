# Implementation Status

> This file records verified repository state and owner-approved architecture. The current architecture-documentation task does not verify or change physical Lenovo state.

- **Plan baseline:** 1.3 — 2026-08-16
- **Current phase boundary:** Lenovo G450 Safety Gate / Ubuntu Server foundation
- **Current state:** Phase 4 and Phase 5A are closed. PR #10 merged ADR-0007. PR #11 merged the repository cleanup gate at `09593cc1874d997fb4888db326068112cf0afd7f`. ADR-0008 accepts the future typed observation/provenance/world-state context foundation as architecture only. Eleven accepted advanced capability families are mandatory long-term BMO scope and are required for eventual full BMO completion; robotics/physical agents are explicitly out of scope by owner decision dated 2026-08-16. None of the eleven advanced systems is implemented or authorized by this update.
- **Current documentation branch:** `phase-01/advanced-context-architecture` for Master Plan v1.3 and ADR-0008 only.
- **Next mandatory physical action after this documentation update is independently reviewed and owner-merged:** create `phase-01/lenovo-control-plane-foundation` from then-current `main`, then perform the Lenovo G450 Safety Gate and Ubuntu Server 24.04.4 LTS AMD64 Foundation.
- **Later phases authorized:** Phase 5B is blocked and Phase 6 is unauthorized until the Lenovo G450 Safety Gate passes. No BMO deployment has occurred.

## Accepted topology

### Lenovo G450 — temporary lightweight always-on control plane

ADR-0007 remains the active host decision. Established planning facts are:

- Intel Core 2 Duo class CPU; do not claim a more specific CPU without verified evidence.
- 4 GB RAM.
- Approximately 128 GB internal storage recorded for planning; exact disk model and type require physical verification.
- Physical RJ-45 Ethernet.
- No useful AI GPU and no local heavy inference.

The operating baseline is Ubuntu Server 24.04.4 LTS AMD64, headless, with no desktop GUI. Preserve Legacy BIOS/MBR compatibility in installation planning, but do not claim the exact firmware boot mode before inspection. DHCP is acceptable for initial installation; any fixed address or DHCP reservation follows network inspection. SSH is required after installation. Services remain private-LAN only, with no public port forwarding.

The Lenovo may provide the Core API and lightweight orchestration, identity/device registry, permissions and approvals, scheduler, audit/event coordination, Mosquitto MQTT, model gateway and ASUS TUF health routing, notifications, service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector remain conditional on measured safety, storage, RAM, and load acceptance. The Lenovo must not run Qwen3.5 4B, BGE-M3 inference, heavy STT/TTS, heavy vision/indexing, a local heavy LLM, or an unrestricted LLM shell.

Because the Lenovo has 4 GB RAM, installation remains minimal and headless. Configure swap only after disk and RAM inspection; admit Docker and services gradually from measured memory, disk, and load pressure. Require SMART monitoring, bounded logs, free-space thresholds, off-device backups, restore evidence, and staged stability gates. Do not add Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, or Grafana without a later ADR and measured need.

ADR-0008 does not add a Lenovo service. Any future low-rate world-state projection on the Lenovo remains subject to the normal safety/resource admission gate; heavy perception, high-rate fusion, model inference, and expensive indexing remain on the ASUS TUF or owning satellite/device.

### ASUS TUF — heavy compute and Windows execution plane

The ASUS TUF retains native Ollama, Qwen3.5 4B as the initial primary generation/orchestration/vision model, BGE-M3 embeddings, heavy speech/vision/indexing, the Windows satellite, isolated browser automation, development, benchmarking, and Codex work. Qwen3.5 9B is deferred, not an active required model, and not a Phase 4 or Phase 5A requirement. When the TUF is unavailable, Lenovo-hosted deterministic functions must degrade honestly rather than making the full backend appear dead.

### Desktop PC — future control-plane upgrade candidate

ADR-0005 and the owner-reported desktop hardware facts are preserved as historical evidence. The desktop PC is not the current deployment authority, active topology node, mandatory safety gate, or Phase 5B prerequisite. A future Lenovo-to-desktop migration requires a new owner-approved host-migration ADR and a separate safety gate.

## Accepted advanced-context architecture

ADR-0008 accepts a future product-owned typed observation/evidence boundary and a permission-aware world-state read model. The decision separates evidence quality, freshness, and conflict state; preserves explicit source authority and provenance; requires deterministic semantic fusion first; and limits model runtimes to bounded permission-filtered context snapshots.

The eleven accepted advanced capability families are: world state, context fusion, active workspace context, engineering/scientific workflows, long-horizon goals, active perception, anomaly intelligence, communications, adaptive personalization, distributed resilience, and spatial/AR interfaces. They are mandatory long-term product targets and full BMO is not complete until all eleven are implemented and accepted, unless a later explicit owner architecture decision de-scopes one.

**Robotics/physical agents are out of scope, not deferred.** There is no planned robot implementation, robot simulation phase, robotics middleware/ROS dependency, robot control API, or robot-specific hardware requirement. Reintroduction would require an explicit future owner scope reversal and a new ADR.

No concrete world-state schema, API route, new runtime service, new dependency, sustained camera session, mobile-local model, or AR implementation is authorized by ADR-0008. Future dependencies and privacy-sensitive systems require their own phase-specific review and gates where applicable.

## Historical branch boundary

- ADR-0003 remains historical and superseded by ADR-0005.
- ADR-0005 is superseded by ADR-0007.
- `phase-01/lenovo-foundation` remains unmerged audit history and must not be merged, rebased, force-pushed, rewritten, or reused.
- Physical Lenovo work begins only from then-current `main` on a new `phase-01/lenovo-control-plane-foundation` branch after this documentation-only architecture update is independently reviewed and owner-merged.

## Verified sequencing state

- PR #7 merged into `main` at `caeb366af121ed3f2dca5239f34346a13f8a031a`.
- PR #8 merged into `main` at `a4a4cf78890c5efe98830a6ecc22757cf9f826f2`; Phase 4 is closed.
- PR #9 merged and closed into `main` at `7d0ec7aa957c5d3b33f4fc7818da0e5cc6382620`; Phase 5A is closed.
- PR #10 merged into `main` at `e8a2ddd6ecb4dac75b09fe6d96ec3071d270de41`; ADR-0007 is the accepted active host architecture.
- PR #11 merged into `main` at `09593cc1874d997fb4888db326068112cf0afd7f`; the repository cleanup gate is closed.
- ADR-0008 is the accepted advanced-context architecture decision on the current documentation branch; it does not advance implementation phases.
- The accepted active stack is Qwen3.5 4B plus BGE-M3 only. Qwen3.5 9B remains deferred.
- The implementation sequence remains **Lenovo G450 Safety Gate → Lenovo Ubuntu Server foundation → Phase 5B deployment/integration acceptance → Phase 6**, followed by the existing roadmap. Advanced-system extensions activate only when their prerequisite phases are reached and explicitly authorized; all eleven accepted systems remain required for eventual full BMO completion.

## Verified Phase 2 and Phase 3 implementation state

- Phase 2 health, configuration, logging, SQLAlchemy/Alembic, PostgreSQL/pgvector Compose, and CI foundation are merged. GitHub CI is authoritative for the PostgreSQL path.
- Phase 3 pins OpenJarvis `1.0.0`, confines direct imports to the adapter, and verifies local-only request, bounded identifiers, trace redaction, contracts, and PostgreSQL integration. PR #5 is merged.

## Phase boundary

This architecture update changes documentation, ADR governance, and governance tests only. It does not install Ubuntu, inspect or modify physical Lenovo hardware, deploy containers, create world-state/context runtime code, start Phase 5B or Phase 6, download models, change the Phase 5A gateway, alter database schema, add dependencies, or change model identities/digests. The next mandatory physical step remains the Lenovo G450 Safety Gate and Ubuntu Server 24.04.4 LTS AMD64 Foundation.