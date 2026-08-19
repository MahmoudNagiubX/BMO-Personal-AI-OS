# Phase 8.5 Completion Report

## Outcome

READY_FOR_PHASE_8_5_INDEPENDENT_REVIEW

The optional advanced local provider is implemented on
`phase-08-5/qwen-9b-heretic-admission` from the exact Phase 8 merge base.
Qwen3.5 4B plus BGE-M3 through Ollama remains the default accepted stack.
Qwen3.5-9B Heretic v2 is explicit, text-only, loopback-only, and never a
silent fallback. Phase 9 was not started.

## Hardware and runtime admission

- llama.cpp build: `b10502-0adcc3bb5`.
- Server executable SHA-256:
  `f620cde4258c202b6b149004643dbd90124d708cee042a8b65397b69777887ec`.
- GGUF SHA-256:
  `8d463c63e2c8759ad263cba59f1fa7a0be9a7cacb59b0fd0a787b7daa31597ad`.
- Endpoint: `127.0.0.1:11435`.
- Profile: 4K context, q8_0 K/V cache, Flash Attention, parallel 1,
  `N_SAFE=20`, GPU split 20/33, host split 13/33, no vision projector,
  12-second idle unload.
- The TUF-to-VENOM reverse tunnel passed for both loopback endpoints; VENOM
  listeners were verified as `127.0.0.1:11434` and `127.0.0.1:11435`.

## Acceptance evidence

- Advanced REST stress: 25/25 passed; 9.207–10.251 second latency; maximum
  67°C; minimum GPU free 778 MiB; sleep/unload passed.
- Switching: 10/10 passed for advanced generation, Qwen4B generation, and
  BGE-M3 embeddings; BGE vectors were 1024-dimensional and finite.
- Switching minimum GPU free was 4165 MiB, maximum temperature 55°C, and
  minimum free RAM was 5,797,990,400 bytes.
- No simultaneous heavy residency, OOM, llama.cpp runner crash, or display
  driver reset was observed.
- Qwen4B and BGE-M3 exact identities and regression smokes passed.

The sanitized machine-readable record is
`docs/phase_reports/evidence/PHASE_08_5_LLAMA_CPP.json`. Its final exact-head
CI field is intentionally an external governance requirement rather than a
self-referential claim.

## Repository implementation

- ModelGateway now supports isolated Ollama and llama.cpp providers,
  deterministic `fast`/`advanced` routing, provider-specific circuits,
  residency coordination, exact model identity, and no fallback.
- Conversation runs persist requested model and executed provider.
- Alembic migration `20260820_0005` adds those nullable audit fields.
- The reverse tunnel configuration and VENOM installation/verifier now permit
  only the two loopback remote listeners.
- ADR-0009 records the architecture, runtime profile, provenance boundary,
  migration, rollback, and security constraints.

## Validation

The repository-side suite passed locally: 423 tests, Ruff, mypy, governance,
secret scanning, and the Phase 8.5 evidence validator. PostgreSQL integration
tests require the repository's configured CI database and remain an external
CI gate.

## Boundaries

No public or LAN model listener was opened. No credentials or model binaries
were committed. No Phase 9 implementation was started and no merge was
performed. Final exact-head GitHub CI must be verified after the final normal
commit and push.
