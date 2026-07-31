# ADR-0002 — Isolate OpenJarvis behind a product-owned adapter

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

OpenJarvis provides useful agent, engine, tool, memory, trace, scheduler, and security primitives, but it is an external alpha-stage framework with an evolving API. Product identity, permissions, data, and device protocols must remain stable if the framework changes.

## Decision

Use OpenJarvis through `packages/openjarvis_adapter/` only. Begin the Phase 3 compatibility spike against release tag `v1.0.0`, commit `e97088f`. No other product module may import OpenJarvis directly. Do not fork initially.

## Rationale

A narrow adapter gains useful infrastructure while preserving replaceability, upgrade control, testability, and product ownership.

## Consequences

### Positive

- Upstream changes are contained.
- Application contracts remain ours.
- A future replacement is feasible.

### Negative / trade-offs

- Adapter code and contract tests add work.
- Some upstream capabilities may require translation or may be rejected.

## Security and privacy impact

External analytics must be disabled. The adapter must sanitize traces, enforce tool boundaries, and prevent upstream defaults from bypassing product permissions.

## Migration and rollback

Every upgrade uses a compatibility branch, pinned tag/commit, contract test report, and ADR update. Roll back by restoring the previous lock and adapter implementation.

## Validation

Phase 3 must prove a local model request, trace translation, analytics disablement, tool-schema behavior, and an import-boundary test.
