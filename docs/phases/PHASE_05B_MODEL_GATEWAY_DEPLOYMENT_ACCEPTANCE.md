# Phase 5B — Model-Gateway Deployment Acceptance

## Status

Security/evidence recovery passed on `phase-05b/model-gateway-deployment-acceptance` and is ready
for independent review. Runtime/model evidence remains preserved, the strict directional tunnel
policy passed live tests, and the concrete evidence validator accepts the reconciled evidence.
Phase 6 is not started.

## Scope

Deploy the accepted Phase 5A gateway contracts on VENOM while inference remains on the ASUS TUF:

```text
VENOM gateway -> 127.0.0.1:11434 -> reverse SSH -> TUF 127.0.0.1:11434 -> Ollama
```

The active identities remain Qwen3.5 4B
`sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`
and BGE-M3 567M
`sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`,
with 1,024-dimensional embeddings. Qwen3.5 9B remains deferred and inactive.

## Security invariants

- Ollama and the reverse listener bind only to loopback.
- No port 11434 UFW rule, router change, cloud provider, or cloud fallback is allowed.
- The persistent tunnel uses a dedicated `bmo-tunnel` Unix identity. Its server-side `Match User`
  policy permits only remote forwarding, denies local/dynamic forwarding with `PermitOpen none`,
  limits remote listening to `127.0.0.1:11434`, and denies password, PTY, agent, X11, and normal
  command authority. Its private key remains only on the TUF.
- The gateway cannot execute tool proposals and does not persist prompts, responses, images,
  vectors, raw provider payloads, or credentials.
- Normal provider-offline state is typed evidence and does not fail the VENOM systemd unit.

## Required acceptance

Real exact-commit evidence must prove available, configuration-only degraded, offline and
recovery states; bounded generation and embedding; data-only tool proposals; retry/circuit and
two-caller concurrency behavior; tunnel, Ollama, and probe restart recovery; loopback-only
listeners; unchanged UFW; acceptable VENOM resource deltas; and reversible deployment. Normal CI
must validate all new logic without depending on either physical host.

The dedicated identity must additionally prove one allowed canonical reverse forward and live
denial of local forwarding, dynamic forwarding, and any alternate remote listen. High-level PASS
booleans never replace concrete generation, embedding, tool, resilience, restart, observability,
resource, security, rollback, Phase 1 monitor, and phase-boundary evidence.

Wake-on-LAN is evaluation-only and may be deferred. The Phase 1 monitor remains active and its
24-hour/seven-day windows remain truthfully subject to ADR-0008's owner waiver.

## Stop conditions

Stop on VENOM SMART, sector, thermal, filesystem, failed-unit, reboot, or Ethernet degradation;
wrong model identity; any public/LAN Ollama listener; cloud fallback; tool execution; unsafe
resource pressure; unconstrained tunneling; or weakened SSH/UFW policy.

## Rollback

Remove the TUF Scheduled Task and stop only the reviewed tunnel. Disable the Phase 5B probe timer
and remove only Phase 5B systemd/key authorization on VENOM. Preserve Phase 1 monitoring,
hardening, historical evidence, models, and the manual proof-of-life workspace. No database
rollback is involved.
