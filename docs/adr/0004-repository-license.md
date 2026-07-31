# ADR-0004 — License original project code under Apache 2.0

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

The project is personal today but may later become a graduation project, portfolio product, research project, startup, or commercial offering. A restrictive non-commercial base would limit those options.

## Decision

License original repository code under Apache License 2.0. Track third-party code, models, voices, and datasets separately and comply with their licenses. Personal data and secrets are not licensed merely because code is open.

## Rationale

Apache 2.0 is permissive, includes an express patent grant, aligns with OpenJarvis, and preserves future personal, academic, and commercial use.

## Consequences

### Positive

- Broad reuse and commercial flexibility.
- Clear patent and notice terms.

### Negative / trade-offs

- Publicly released original code may be reused by others under the license.
- Third-party and model licenses still require separate review.

## Security and privacy impact

Repository publication must never include personal datasets, credentials, private configurations, or production artifacts.

## Migration and rollback

The owner may change licensing before accepting outside contributions. Relicensing after external contributions requires contributor rights or consent.

## Validation

Keep `LICENSE`, `LICENSE_INVENTORY.md`, and `THIRD_PARTY_NOTICES.md` current before every public release.
