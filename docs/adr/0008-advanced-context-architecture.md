# ADR-0008 — Adopt typed observation, provenance, and world-state context architecture

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

BMO already requires typed tools, deterministic policy and execution, explicit approvals, structured audit, transparent memory, honest degraded states, Home Assistant authority for room automation, and a modular-monolith-first architecture. The roadmap, however, needs one product-owned evidence contract that can safely normalize future state arriving from Windows, Android, Home Assistant, MQTT devices, calendar/communications integrations, browser/research workers, telemetry, and explicit perception sessions.

A researched architecture proposal evaluated twelve capability families: world state, context fusion, active workspace context, engineering/scientific workflows, long-horizon goals, active visual perception, robotics/physical agents, anomaly intelligence, communications, adaptive personalization, distributed resilience, and spatial/AR interfaces. The proposal is architecture input, not implementation authority. After review, Mahmoud accepted eleven capability families as mandatory long-term BMO scope and explicitly rejected robotics/physical agents from BMO scope.

Without a common evidence model, future domains could conflate model inference with verified state, use stale data as current truth, silently overwrite contradictory sources, retain sensitive media too broadly, or create a second authority beside the domain that actually owns the state.

## Decision

BMO adopts a product-owned **typed observation and evidence architecture** as the common contextual boundary for future in-scope capabilities. This ADR defines architecture only; it does not authorize runtime implementation in the current phase.

### 1. Observation envelope

Future sources and verified action results that enter the contextual layer will normalize into a typed `ObservationEnvelope` (or equivalent product-owned contract) carrying, at minimum, semantics for:

- stable observation identity and schema version;
- source kind and source device/integration identity where applicable;
- subject kind and subject identity;
- observed time and received time;
- validity/expiry semantics;
- typed value and unit where applicable;
- evidence quality;
- confidence when meaningful and deterministically defined;
- sensitivity and retention class;
- authority domain and authoritative, mirrored, or inferred status;
- verification method;
- correlation/run identifiers where applicable;
- source reference/provenance.

Exact field names and persistence schema remain implementation decisions for the phase that introduces the contract.

### 2. Evidence quality, freshness, and conflict are separate dimensions

BMO will not encode staleness or contradiction as evidence-quality values.

- **Evidence quality:** `verified`, `reported`, `inferred`, `estimated`, or `unknown`.
- **Freshness state:** `fresh`, `aging`, `stale`, `expired`, or `unknown`, with thresholds defined per signal/domain.
- **Conflict state:** independent metadata indicating whether relevant evidence is consistent, conflicting, or unresolved.

A verified reading may be stale, a fresh reading may be inferred, and multiple individually valid observations may conflict. These dimensions therefore remain separate.

### 3. Derived context claims

A future `ContextClaim` (or equivalent product-owned contract) represents a derived statement built from one or more observations. A claim remains traceable to supporting evidence and carries derivation time, validity, confidence where applicable, derivation rule/version or method, contradiction state, and sensitivity.

Model output may contribute an observation labeled as inference. It is never silently promoted to verified or authoritative state.

### 4. World state is a read model, not a second authority

A future World State capability is a permission-aware, time-aware, evidence-backed contextual projection. It does not replace domain ownership.

Examples of authority remain domain-specific:

- Home Assistant remains authoritative for selected room entities and automation state.
- The Windows satellite is authoritative only for Windows telemetry it directly measures or verifies.
- Calendar providers remain authoritative for provider-backed calendar state.
- The goal domain will own BMO goal execution state when that domain is authorized.
- The memory domain owns accepted durable memories.
- Model/vision inference is contextual evidence, not physical or account authority.

A lower-authority or lower-quality observation cannot silently overwrite verified authoritative state. Conflicts remain inspectable.

### 5. Freshness and provenance are first-class

Every contextual result used for reasoning or action must expose enough metadata to determine whether it is still valid and where it came from. A stale or unavailable source degrades to stale/unknown rather than being presented as current truth.

Source removal, revocation, or disconnection invalidates or downgrades dependent claims according to deterministic policy.

### 6. Deterministic semantic fusion first

Future semantic context fusion begins with explicit, versioned rules over typed observations. Time alignment, source lineage, freshness, contradiction handling, cycle prevention, and confidence policy are deterministic product concerns.

The LLM must not invent calibrated numeric confidence or become the authority that reconciles source truth.

### 7. Bounded context snapshots

Conversation, planning, proactive, and future goal runtimes receive small permission-filtered context snapshots, not unrestricted access to the entire world-state store or raw event history. Every decision-relevant contextual field remains traceable to evidence outside the prompt.

### 8. Privacy and retention defaults

Raw camera frames, desktop recordings, raw audio, continuous location trails, broad notification history, and unbounded high-frequency sensor telemetry are not durable context by default.

Explicit capture/recording use cases require purpose, consent where applicable, sensitivity classification, bounded retention, deletion controls, and audit. Derived contextual observations may persist only under the normal owner-controlled retention policy.

### 9. Resource and topology constraints remain unchanged

The Lenovo G450 remains the temporary lightweight control plane under ADR-0007. If a future world-state implementation is admitted there, it is limited to low-rate ingestion, current-state projection, freshness checks, and bounded context queries only after Lenovo safety/resource gates pass.

Heavy perception, high-rate fusion, model inference, and expensive indexing remain on the ASUS TUF or the owning satellite/device. This ADR does not authorize new Lenovo services now.

### 10. Eleven accepted advanced capability families are mandatory long-term targets

The accepted in-scope advanced capability families are:

1. Unified World State Engine.
2. Sensor and Context Fusion.
3. Active Workspace Context.
4. Engineering and Scientific Copilot.
5. Long-Horizon Goal Engine.
6. Active Visual Perception.
7. Anomaly and Event Intelligence.
8. Communications Hub.
9. Adaptive Personalization.
10. Distributed Intelligence and Graceful Failover.
11. Spatial / AR Interface.

These are mandatory long-term product targets. “Future” or “planned later” means sequenced after prerequisites, not optional permanent omission. Their roadmap placement does not authorize them early.

### 11. Robotics and physical agents are explicitly out of scope

The source proposal included robotics/physical agents. Mahmoud explicitly rejected that capability on 2026-08-16.

BMO therefore has no planned:

- physical robot or mobile robotic platform;
- robotics simulation phase;
- robot middleware or ROS dependency;
- robot mission/control API;
- robot-specific data domain;
- motor/actuator control surface.

Robotics is **not deferred** and is **not a completion requirement**. Reintroducing it requires a future explicit owner scope reversal and a new ADR.

## Explicitly deferred implementation decisions

This ADR does **not** approve or lock:

- concrete PostgreSQL table names or migrations for world state/context;
- new API routes or WebSocket event names;
- creation of future domain directories/modules before their phase begins;
- VS Code extension, Windows UI Automation, Windows Graphics Capture, Jupyter, KiCad IPC, scikit-learn, llama.cpp, ARCore, or additional messaging-platform dependencies;
- learned anomaly models;
- mobile-local LLM inference;
- persistent camera/screen monitoring;
- cloud spatial anchors or persistent room maps;
- proposal-suggested performance numbers.

Any dependency addition must be pinned, license-recorded, security-reviewed, resource-measured where relevant, and introduced only by the phase that needs it. Sustained perception, mobile-local inference, and cloud/spatial persistence require their own later privacy/security architecture gates when approached.

## Rationale

The accepted foundation extends ADR-0001 rather than replacing it: BMO remains a modular monolith with independently deployed satellites where hardware/execution ownership requires them. A common evidence contract lets future features share provenance and freshness semantics without becoming a collection of uncontrolled services.

Separating evidence quality, freshness, conflict, and authority improves correctness over a single mixed status field. Preserving domain authority prevents a contextual projection or model inference from becoming an accidental source of truth. Deterministic fusion and bounded context snapshots preserve auditability, privacy, and predictable resource use while enabling richer JARVIS-style context later.

The robotics rejection keeps the product focused on a personal AI operating system across existing computers, mobile, room automation, and approved peripherals rather than expanding into a separate robotics program.

## Consequences

### Positive

- Future contextual features share one auditable evidence vocabulary.
- BMO can distinguish verified, inferred, stale, and conflicting information without conflating them.
- Domain authorities remain intact while the agent gains richer context.
- Context supplied to models stays bounded, scoped, and provenance-backed.
- Future systems can degrade honestly when sources or the TUF are unavailable.
- Eleven accepted advanced systems remain clear mandatory long-term targets.
- Robotics hardware, middleware, simulation, and safety-program complexity are removed from BMO scope.

### Negative / trade-offs

- Future integrations must supply provenance, freshness, and authority metadata rather than pushing ad-hoc values directly into prompts.
- Context fusion and invalidation require careful deterministic policy and synthetic evaluation.
- More metadata increases schema/test complexity when implementation begins.
- BMO will not provide physical mobile-agent/robot capabilities under the current product scope.

## Security and privacy impact

The contextual layer introduces risks including source spoofing, stale-context actions, authority confusion, prompt injection carried by messages/screens/documents/sensors, model inference being elevated to truth, sensitive-context leakage, retention creep, and offline/multi-master conflicts.

Required mitigations include authenticated source identity, revocable scopes, provenance, separate freshness/conflict metadata, sensitivity and retention filtering, bounded snapshots, deterministic authority rules, fail-closed action policy, prompt-injection isolation for external content, and no default durable raw-media retention.

No consequential action may be justified solely by an unverified derived claim where policy requires an authoritative or directly verified source.

## Migration and rollback

This ADR and its associated master-plan update are documentation/governance changes only. They add no database migration, runtime service, dependency, model, API, or physical deployment.

Future implementations are additive and require their own migrations, backup/restore evidence, and rollback plans in the phase that introduces them.

Before implementation depends on this ADR, rollback is a normal revert of the architecture-documentation PR. Reverting this ADR does not change ADR-0007, the Lenovo/TUF topology, model identities, or the current physical safety gate.

## Validation

For this architecture update:

- governance checks require ADR-0008 and Master Plan v1.3;
- tests lock that the advanced context architecture does not advance Phase 5B or Phase 6;
- tests lock eleven accepted advanced capability families as mandatory long-term scope;
- tests lock robotics/physical agents as explicitly out of scope;
- the current Lenovo/TUF topology, model stack, no-cloud-default, and historical branch boundaries remain unchanged;
- CI must pass on the exact documentation/governance PR head.

When future in-scope implementation begins, acceptance includes synthetic tests for freshness, authority, conflicting evidence, source removal/offline behavior, sensitive-scope filtering, bounded context snapshots, provenance integrity, prompt injection, and raw-media non-retention.