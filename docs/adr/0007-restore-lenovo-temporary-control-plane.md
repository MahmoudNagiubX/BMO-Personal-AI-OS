# ADR-0007 — Restore Lenovo G450 as temporary always-on control plane

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Mahmoud
- **Supersedes:** ADR-0005
- **Superseded by:** None

## Context

The desktop PC selected by ADR-0005 is no longer the active BMO control-plane host for the current implementation window. The owner has selected the Lenovo G450 as a practical temporary host while preserving the ASUS TUF F15 as the heavy AI and Windows execution plane. ADR-0003 remains historical evidence of the earlier control/compute split; it is not reactivated.

Established Lenovo planning facts are a Core 2 Duo class CPU, 4 GB RAM, approximately 128 GB internal storage, physical RJ-45 Ethernet, and no useful AI GPU. The exact CPU, disk type/model, firmware boot mode, battery, fan, thermal, storage, and power condition require physical verification. The desktop hardware records in ADR-0005 remain preserved as historical evidence and a future upgrade candidate.

## Decision

Use the Lenovo G450 as the temporary lightweight always-on BMO control plane. Its operating baseline is Ubuntu Server 24.04.4 LTS AMD64, headless, with no desktop GUI. Preserve Legacy BIOS/MBR compatibility in installation planning, but do not claim an exact boot mode until inspection.

The Lenovo may provide the Core API and lightweight orchestration, identity/device registry, permissions and approvals, scheduler, audit/event coordination, Mosquitto MQTT, model gateway and ASUS TUF health routing, lightweight notifications/service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector are admitted only after the relevant storage, RAM, and load gates pass. When the TUF is unavailable, Lenovo-hosted deterministic functions must degrade honestly rather than reporting the entire backend as dead.

The Lenovo must not run Qwen3.5 4B, BGE-M3 inference, a local heavy LLM, heavy STT/TTS, heavy vision/indexing, or an unrestricted LLM shell. The ASUS TUF retains native Ollama, Qwen3.5 4B primary generation/orchestration/vision, BGE-M3 embeddings, heavy speech/vision/indexing, the Windows satellite, isolated browser worker, development, benchmarking, and Codex work. Qwen3.5 9B remains deferred and non-required.

The desktop PC is a future control-plane upgrade or migration candidate, not an active node, deployment authority, mandatory safety gate, or Phase 5B prerequisite. A later Lenovo-to-desktop migration requires a new owner-approved ADR and a new safety gate.

## Resource, network, and security policy

Keep the Lenovo minimal and headless. Configure swap only after disk and RAM inspection; do not invent a final size. Admit Docker and services gradually from measured memory, storage, and load pressure. Use bounded logs, SMART monitoring, free-space thresholds, off-device backups, and restore evidence. Do not add Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, or Grafana without a later ADR and measured need.

Use wired RJ-45 Ethernet where available. DHCP is acceptable during initial installation; any fixed address or DHCP reservation follows network inspection. SSH is required after installation. Services are private-LAN only, with no public port forwarding. Future Lenovo/TUF communication uses authenticated, scoped interfaces.

## Consequences

### Positive

- A low-power host can retain deterministic control-plane responsibilities while the TUF is off.
- Heavy inference remains on the proven ASUS TUF model node.
- Stable product interfaces remain host-replaceable.

### Negative / trade-offs

- Four GB of RAM sharply limits the services that can be accepted at once.
- Storage, thermals, fan, battery, and power safety must be verified before any deployment.
- Home Assistant and PostgreSQL/pgvector may need to remain deferred if measured resource gates fail.

## Migration and rollback

The historical `phase-01/lenovo-foundation` branch must not be merged, rebased, force-pushed, rewritten, or reused. After this ADR is independently reviewed and owner-merged, physical Lenovo work starts from then-current `main` on a new `phase-01/lenovo-control-plane-foundation` branch.

Before physical deployment, rollback is a normal revert of this architecture update followed by a new owner-approved host ADR. Do not silently reactivate ADR-0005 or deploy the desktop without its own renewed safety gate.

## Validation

- Governance tests lock ADR-0007, ADR-0005 supersession, the Lenovo/TUF/Desktop role split, the Ubuntu Server baseline, Phase 5A merge status, the Lenovo G450 Safety Gate, and Qwen3.5 9B deferral.
- The Lenovo G450 Safety Gate must physically verify hardware, storage, memory, thermals, fans, battery, Ethernet, power behavior, Ubuntu Server installation/hardening, backups, restore, and staged stability before Phase 5B.
