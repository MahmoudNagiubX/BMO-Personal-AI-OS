# Implementation Status

> This file records verified repository state and owner-approved architecture. No physical Lenovo state is verified by this documentation/governance update.

- **Plan baseline:** 1.2 — 2026-08-15
- **Current phase boundary:** Post-Phase 5A physical deployment gate
- **Current state:** PR #9 is merged and Phase 5A is closed. The active architecture is updated by ADR-0007 on `architecture/lenovo-temporary-control-plane`; it remains subject to independent review, final-head GitHub CI, and owner merge.
- **Current branch target:** `architecture/lenovo-temporary-control-plane`
- **Next mandatory action after owner merge:** Lenovo G450 Safety Gate and Ubuntu Server foundation.
- **Later phases authorized:** Phase 5B and Phase 6 remain unauthorized until the Lenovo G450 Safety Gate passes.

## Accepted topology

### Lenovo G450 — temporary lightweight always-on control plane

ADR-0007 is the active host decision. Established planning facts are:

- Intel Core 2 Duo class CPU; do not claim a more specific CPU without verified evidence.
- 4 GB RAM.
- Approximately 128 GB internal storage recorded for planning; exact disk model and type require physical verification.
- Physical RJ-45 Ethernet.
- No useful AI GPU and no local heavy inference.

The operating baseline is Ubuntu Server 24.04.4 LTS AMD64, headless, with no desktop GUI. Preserve Legacy BIOS/MBR compatibility in installation planning, but do not claim the exact firmware boot mode before inspection. DHCP is acceptable for initial installation; any fixed address or DHCP reservation follows network inspection. SSH is required after installation. Services remain private-LAN only, with no public port forwarding.

The Lenovo may provide the Core API and lightweight orchestration, identity/device registry, permissions and approvals, scheduler, audit/event coordination, Mosquitto MQTT, model gateway and ASUS TUF health routing, notifications, service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector remain conditional on measured safety, storage, RAM, and load acceptance. The Lenovo must not run Qwen3.5 4B, BGE-M3 inference, heavy STT/TTS, heavy vision/indexing, a local heavy LLM, or an unrestricted LLM shell.

Because the Lenovo has 4 GB RAM, installation remains minimal and headless. Configure swap only after disk and RAM inspection; admit Docker and services gradually from measured memory, disk, and load pressure. Require SMART monitoring, bounded logs, free-space thresholds, off-device backups, restore evidence, and staged stability gates. Do not add Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, or Grafana without a later ADR and measured need.

### ASUS TUF — heavy compute and Windows execution plane

The ASUS TUF retains native Ollama, Qwen3.5 4B as the initial primary generation/orchestration/vision model, BGE-M3 embeddings, heavy speech/vision/indexing, the Windows satellite, isolated browser automation, development, benchmarking, and Codex work. Qwen3.5 9B is deferred, not an active required model, and not a Phase 4 or Phase 5A requirement. When the TUF is unavailable, Lenovo-hosted deterministic functions must degrade honestly rather than making the full backend appear dead.

### Desktop PC — future control-plane upgrade candidate

ADR-0005 and the owner-reported desktop hardware facts are preserved as historical evidence. The desktop PC is not the current deployment authority, active topology node, mandatory safety gate, or Phase 5B prerequisite. A future Lenovo-to-desktop migration requires a new owner-approved host-migration ADR and a separate safety gate.

## Historical branch boundary

- ADR-0003 remains historical and superseded by ADR-0005.
- ADR-0005 is superseded by ADR-0007.
- `phase-01/lenovo-foundation` remains unmerged audit history and must not be merged, rebased, force-pushed, rewritten, or reused.
- After ADR-0007 is owner-merged, physical Lenovo work begins from then-current `main` on a new `phase-01/lenovo-control-plane-foundation` branch.

## Verified sequencing state

- PR #7 merged into `main` at `caeb366af121ed3f2dca5239f34346a13f8a031a`.
- PR #8 merged into `main` at `a4a4cf78890c5efe98830a6ecc22757cf9f826f2`; Phase 4 is closed.
- PR #9 merged and closed into `main` at `7d0ec7aa957c5d3b33f4fc7818da0e5cc6382620`; Phase 5A is closed.
- The accepted active stack is Qwen3.5 4B plus BGE-M3 only. Qwen3.5 9B remains deferred.
- The accepted sequence is **architecture update restoring Lenovo → Lenovo G450 Safety Gate → Lenovo Ubuntu Server foundation → Phase 5B deployment/integration acceptance → Phase 6**.

## Verified Phase 2 and Phase 3 implementation state

- Phase 2 health, configuration, logging, SQLAlchemy/Alembic, PostgreSQL/pgvector Compose, and CI foundation are merged. GitHub CI is authoritative for the PostgreSQL path.
- Phase 3 pins OpenJarvis `1.0.0`, confines direct imports to the adapter, and verifies local-only request, bounded identifiers, trace redaction, contracts, and PostgreSQL integration. PR #5 is merged.

## Phase boundary

This update changes documentation, ADR governance, and governance tests only. It does not install Ubuntu, inspect or modify physical Lenovo hardware, deploy containers, start Phase 5B, download models, change the Phase 5A gateway, alter database schema, or change model identities/digests. The next mandatory step after owner merge is the Lenovo G450 Safety Gate and Ubuntu Server foundation.
