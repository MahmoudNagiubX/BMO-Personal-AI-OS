# Advanced Context Proposal — Architecture Review Record

- **Date:** 2026-08-16
- **Reviewed input:** `BMO_ADVANCED_SYSTEMS_MASTER_PLAN_EXPANSION(1).md`
- **Canonical baseline reviewed:** Master Plan v1.2, ADR-0001 through ADR-0007, `AGENTS.md`, and `docs/IMPLEMENTATION_STATUS.md`
- **Decision authority:** Mahmoud
- **Result:** Accepted with modifications and explicit deferrals

## Accepted into Plan v1.3 / ADR-0008

- A product-owned typed observation/evidence boundary for future contextual sources and verified results.
- Explicit provenance, source identity, verification method, sensitivity, retention, validity, and authority semantics.
- A permission-aware World State capability as a bounded contextual **read model**, never a second authority for Home Assistant, memory, goals, devices, or external providers.
- Derived `ContextClaim` semantics with supporting evidence and deterministic derivation metadata.
- First-class freshness and source invalidation.
- Preservation of contradictory observations instead of unconditional last-write/newest-wins behavior.
- Deterministic semantic context fusion before model-driven fusion.
- Bounded permission-filtered context snapshots for model runtimes rather than unrestricted access to the full world/event store.
- No durable raw camera/screen/audio/high-rate telemetry by default.
- Twelve advanced capability families as future roadmap architecture: World State, context fusion, active workspace context, engineering/scientific workflows, long-horizon goals, active visual perception, robotics/physical agents, anomaly intelligence, communications, adaptive personalization, distributed resilience, and spatial/AR.
- Lettered future roadmap placement while preserving the existing numbered phase sequence and current Lenovo gate.
- High-level physical-agent commands only through an independent local safety controller; no direct model-to-motor authority.
- Supported communications connectors must use scoped identities, exact previews, approvals, verification, and prompt-injection isolation.
- Durable personalization remains inspectable, editable, deletable, scope-limited, and owner-controlled.
- Long-running goals use persisted bounded state/checkpoints/budgets rather than an unrestricted LLM loop.
- Anomaly detection begins with deterministic rules/trends before learned methods.
- Distributed behavior retains central authority and honest degradation instead of multi-master writes or silent cloud fallback.

## Accepted with modification

### Separate evidence quality, freshness, and conflict

The proposal listed `stale` and `conflicting` alongside `verified`, `reported`, `inferred`, and `estimated` under one `ObservationQuality` concept. Plan v1.3 / ADR-0008 intentionally separates them because they answer different questions:

- **Evidence quality** answers how the value was established.
- **Freshness** answers whether that value is still temporally usable.
- **Conflict state** answers whether other relevant evidence disagrees.

A reading can be verified but stale, or fresh but inferred. A conflict can exist between multiple otherwise valid observations. Keeping these dimensions separate avoids ambiguous policy and makes validation/action gating deterministic.

### Candidate technologies remain candidates

The proposal’s references to Windows UI/capture APIs, VS Code extension APIs, Jupyter, KiCad IPC, ROS 2, statistical anomaly libraries, Android local inference, ARCore, and additional communications platforms are treated as feasibility research, not locked dependency choices. Their owning phases must verify current official APIs, versions, licensing, security/privacy impact, hardware cost, and rollback before introduction.

### Performance numbers remain measurement hypotheses

Proposal performance targets are not copied into the locked plan. Each advanced capability receives measurable acceptance targets only after the real implementation path and hardware baseline are known.

## Deferred — not authorized by this architecture update

- concrete world-state/context PostgreSQL table names, indexes, or migrations;
- concrete REST/WebSocket paths or event names;
- creation of future module/service directories;
- new runtime processes or containers;
- new dependencies;
- sustained or room camera monitoring;
- physical robotics;
- learned anomaly models;
- mobile-local LLM inference;
- AR/spatial runtime or cloud anchors;
- broad multi-platform communications implementation;
- any Phase 5B, Phase 6, or later-phase code.

## Current boundary preserved

Repository cleanup PR #11 is merged at `09593cc1874d997fb4888db326068112cf0afd7f`. This architecture update is documentation/governance only. The next mandatory physical work remains the Lenovo G450 Safety Gate and Ubuntu Server 24.04.4 LTS AMD64 Foundation on a new `phase-01/lenovo-control-plane-foundation` branch after this PR is independently reviewed and owner-merged.

Phase 5B remains blocked and Phase 6 remains unauthorized until the Lenovo safety gate passes.
