# ADR-0009 — Isolate the optional advanced model through llama.cpp

- **Status:** Accepted for Phase 8.5 implementation
- **Date:** 2026-08-20
- **Deciders:** Mahmoud
- **Supersedes:** The deferred-only Qwen3.5 9B posture in ADR-0006 for this measured optional path
- **Superseded by:** None

## Context

The accepted Qwen3.5 4B plus BGE-M3 Ollama stack remains stable, but the
Ollama 0.32.5 Windows CUDA runner repeatedly failed for the owner-approved
Qwen3.5-9B Heretic v2 Q4_K_M artifact with CUDA shared-object initialization
and `0xc0000409` process termination. The pinned official llama.cpp b10502
CUDA runtime passed the bounded ASUS TUF admission profile with partial GPU
offload and host RAM, including 25/25 generations, repeated sleep/unload, and
10/10 fast/advanced/BGE switching cycles.

## Decision

Keep Ollama 0.32.5 as the required provider for Qwen3.5 4B and BGE-M3. Add
llama.cpp b10502 only as an optional, explicitly selected provider for
`qwen3.5-heretic:9b-q4km`. The advanced provider is local-only, text-only,
generation/chat-only, loopback-bound on `127.0.0.1:11435`, and has no cloud or
hidden fallback path.

The measured runtime profile is:

- exact GGUF SHA-256:
  `8d463c63e2c8759ad263cba59f1fa7a0be9a7cacb59b0fd0a787b7daa31597ad`;
- llama.cpp build `b10502-0adcc3bb5`;
- context 4096, q8_0 K/V cache, Flash Attention on, parallel 1;
- `N_SAFE=20`, 20/33 layers on the GPU and 13/33 on host RAM;
- no vision projector, speculative decoding, advanced tools, or 8K initial
  context;
- one heavy model resident at a time, with verified sleep/unload before
  switching to Ollama 4B/BGE.

The model gateway owns deterministic provider routing, provider/model circuit
isolation, a shared inference guard, residency checks, exact identity
verification, requested/actual audit fields, and fail-closed advanced
unavailability. Conversation callers select `fast` or `advanced`; advanced
failure never silently falls back to 4B.

The cross-host identity contract uses the stable GGUF filename
`Qwen3.5-9B-ultra-uncensored-heretic-v2-Q4_K_M.gguf`, not a path derived from
the VENOM host filesystem. The VENOM provider compares that filename with the
basename reported by the TUF llama-server, while the TUF launcher separately
verifies the full Windows path and exact GGUF SHA-256 before serving it.

The TUF keeps Ollama on loopback `127.0.0.1:11434`. The existing dedicated
key-only reverse SSH trust path additionally forwards VENOM loopback
`127.0.0.1:11435` to the TUF llama.cpp loopback endpoint. No LAN/public
listener, router change, GatewayPorts setting, or administrative SSH change
is permitted.

## Consequences

- Core availability requires 4B and BGE; advanced missing or unhealthy status
  is surfaced separately and does not make the core appear offline.
- The advanced provider has its own circuit and bounded timeout; failures do
  not trip Ollama circuits.
- A wrong build, path, model hash, listener, or residency state blocks the
  launcher/request rather than guessing or falling back.
- The Heretic artifact is owner-approved and local-only; it is not described
  as an official Qwen release and is not redistributed by this repository.

## Migration and rollback

The forward migration `20260820_0005` adds nullable requested-model and
executed-provider fields to `agent_runs` without rewriting historical rows.
Rollback is a normal Git revert plus a normal Alembic downgrade to
`20260819_0004`; stop the dedicated llama.cpp launcher and remove only its
owned reverse-forward argument while preserving the accepted 4B/BGE tunnel.

## Validation

The external acceptance record includes exact GGUF/build identity, loopback
bind, 25/25 REST stress, sleep/unload, 10/10 switching, 4B/BGE regression,
zero observed OOM/runner-crash/display-reset signatures, and the repository
test/CI results. Independent review remains required before owner merge.
