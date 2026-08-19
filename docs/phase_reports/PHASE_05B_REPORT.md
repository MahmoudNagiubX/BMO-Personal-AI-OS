# Phase 5B Completion Report

## Outcome

Phase 5B runtime/model acceptance and its narrow security/evidence recovery passed on 2026-08-19.
PR #15 is ready for independent security review, remains draft, and is unmerged.
Phase 6 was not started.

## Exact deployment

- Branch/base: `phase-05b/model-gateway-deployment-acceptance` from
  `939e6fc3ec4ec97aca2218b8ffbc60f738fd8210`.
- VENOM deployed package: `e902e85dc6651d63f536a34516b31eb29c778b5c`.
- TUF persistence and security tooling tested through `e902e85dc6651d63f536a34516b31eb29c778b5c`.
- Ollama 0.32.5, loopback only, with the accepted conservative CUDA lifecycle.
- Qwen3.5 4B and BGE-M3 matched their locked digests; Qwen3.5 9B remained deferred.

## Physical acceptance

The transport remains TUF `127.0.0.1:11434` to VENOM `127.0.0.1:11434`. Recovery moved the key to
the dedicated `bmo-tunnel` identity with `AllowTcpForwarding remote`, `PermitOpen none`, and only
`PermitListen 127.0.0.1:11434`. The canonical reverse forward succeeded; local forwarding,
dynamic forwarding, and an alternate remote listener were each denied live. Normal `venom` admin
SSH remained available and root SSH remained denied.

Real VENOM calls proved available, configuration-only degraded, offline, and recovery states.
Generation completed in 7,029.044 ms with three output usage units. One BGE-M3 embedding completed
in 4,153.548 ms with exactly 1,024 finite dimensions. One validated tool proposal returned as data
with no execution authority. No generated content or embedding values were retained.

Transport disruption opened the circuit after two attempts, made the next call fail fast with zero
attempts, admitted one successful half-open probe, and closed. With exactly two callers, the first
completed and the second received typed `busy`. Scheduled tunnel start/stop, Ollama stop/start, and
the VENOM probe restart all recovered correctly. Offline observations exited successfully and
created no failed systemd unit.

## Resource and safety result

VENOM swap remained zero and root usage remained 9%. Available memory changed from 3,540,463,616
to 3,545,845,760 bytes; root data increased 39,358,464 bytes. Maximum observed temperature changed
from 51°C to 52°C. No persistent probe process or failed unit remained.

The latest privileged Phase 1 sample at `2026-08-19T07:31:29Z` was healthy: 38°C, 9% root usage,
and SMART counters 5/197/198 all zero. The stability windows remain waiting under ADR-0008 and
monitoring remains active. Windows reports Ethernet magic-packet and pattern wake enabled;
end-to-end WOL remains unverified/deferred and is not a blocker.

## Validation

- Full pytest: 270 passed and three PostgreSQL cases skipped locally because
  `BMO_TEST_DATABASE_URL` was unset; canonical non-integration validation passed.
- Ruff, formatting, mypy, governance, secret guard, pre-commit, and diff checks passed.
- Security-fix exact-head GitHub CI run 97 passed; final evidence-head CI is required after commit.
- Twenty-three required validator rejection regressions, six supporting Phase 5B tests, and the
  concrete committed-evidence validation passed.

## Security, rollback, and boundary

No password, private key, model content, embedding values, raw provider data, or personal data was
stored. No router/UFW exposure, Phase 5A contract, model identity, cloud fallback, tool authority,
or historical Phase 1 evidence changed.

Rollback stops/removes the limited TUF task and exact tunnel, validates SSH configuration, removes
only the `bmo-tunnel` Match policy and identity, reloads SSH, and disables only the Phase 5B probe
deployment. The exact pre-change backup remains under `/var/lib/bmo-phase5b`. Rollback preserves
models, normal admin SSH, hardening, Phase 1 monitoring, and evidence. No database rollback is
needed.

Sanitized evidence: `infrastructure/home_server/evidence/phase_05b_model_gateway.json`.
