# ADR-0006 — Initial local model stack

- **Status:** Accepted
- **Date:** 2026-08-07
- **Deciders:** Mahmoud
- **Supersedes:** The active Qwen 3.5 9B initial-model requirement
- **Superseded by:** None

## Context

Qwen3.5 9B was investigated on the ASUS TUF. The Ollama Windows runner failed with HTTP 500 responses, `0xc0000409` termination, and CUDA shared-object initialization failures at safe temperatures. Direct llama.cpp work exposed a GGUF metadata mismatch and then a missing `blk.0.ssm_dt.bias` tensor after a metadata-only repair. Official-source recovery required a large download and conversion path that repeatedly failed on transport reliability.

## Decision

Use Qwen3.5 4B as the initial local model for generation, conversation, intent, orchestration, vision, structured output, and typed tool-call data. Use BGE-M3 for embeddings. Codex is the coding specialist. Qwen3.5 9B is deferred, not automatically downloaded or restored, and is not required for MVP or Phase 4 acceptance.

## Consequences

The initial stack remains local-first and bounded. Deterministic product code continues to own authorization, approvals, validation, execution, retries, and verification. A larger local model may be evaluated later through a new measured owner-approved decision.

## Migration and rollback

Historical 9B reports and commits remain audit evidence. The active local 9B tag is decommissioned. A future model-stack change requires a new ADR and measured evaluation; rollback is a normal revert of this ADR before deployment.

## Validation

Governance tests protect the 4B/BGE-M3/Codex roles and 9B deferral. Phase 4 acceptance covers Qwen3.5 4B and BGE-M3 only.
