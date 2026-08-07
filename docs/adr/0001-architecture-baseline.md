# ADR-0001 — Personal AI OS architecture baseline

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

The project needs one durable architecture that can unify personal memory, AI reasoning, safe device actions, room automation, voice, and multiple clients without becoming an unsafe monolithic script.

## Decision

Build a local-first monorepo that begins as a modular monolith plus independently deployable device agents. Use a central identity, permission, audit, and memory model. Use typed tools and deterministic services around a bounded agent runtime.

Python 3.12 and FastAPI are the backend baseline; PostgreSQL/pgvector are the data baseline; Flutter is the product-client baseline; Docker Compose is the deployment baseline.

Host selection is governed by the current compute/control ADR. ADR-0005 is the active decision for the desktop home-server control plane and ASUS TUF compute plane.

## Rationale

This matches Mahmoud's skills, keeps early operations simple, preserves strong module boundaries, and allows selected services or satellites to be separated only when deployment needs justify it.

## Consequences

### Positive

- One source of truth and permission model.
- Easier local development and testing.
- Clear evolution path without premature microservices.
- Host hardware can be replaced behind stable interfaces.

### Negative / trade-offs

- The modular monolith requires discipline to prevent framework coupling.
- The always-on host requires measured service budgets, monitoring, backups, and staged stability acceptance.

## Security and privacy impact

Local-first defaults reduce data exposure, while central authorization and audit prevent each client from inventing its own trust model.

## Migration and rollback

Modules may later become services through versioned interfaces. Hardware may change behind stable service contracts. Rollback is to the last tagged modular-monolith release and a verified database backup.

## Validation

Architecture tests, import-boundary tests, phase acceptance checks, host stability gates, and a master-plan review at each major milestone.
