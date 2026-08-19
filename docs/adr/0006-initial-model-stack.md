# ADR-0006 — Initial local model stack

- **Status:** Accepted
- **Date:** 2026-08-07
- **Deciders:** Mahmoud
- **Supersedes:** The active Qwen 3.5 9B initial-model requirement
- **Superseded by:** ADR-0009 for the optional advanced local-provider path

## Context

Qwen3.5 9B was investigated on the ASUS TUF. The Ollama Windows runner failed with HTTP 500 responses, `0xc0000409` termination, and CUDA shared-object initialization failures at safe temperatures. Direct llama.cpp work exposed a GGUF metadata mismatch and then a missing `blk.0.ssm_dt.bias` tensor after a metadata-only repair. Official-source recovery required a large download and conversion path that repeatedly failed on transport reliability.

## Decision

Use Qwen3.5 4B as the initial local model for generation, conversation, intent, orchestration, vision, structured output, and typed tool-call data. Use BGE-M3 for embeddings. Codex is the coding specialist. Qwen3.5 9B is not part of the accepted Phase 4 baseline; its optional owner-approved llama.cpp admission is defined separately by ADR-0009 and is never required for MVP or default operation.

## Consequences

The initial stack remains local-first and bounded. Deterministic product code continues to own authorization, approvals, validation, execution, retries, and verification. The optional advanced provider is separately measured, local-only, text-only, and never a silent fallback.

## Migration and rollback

Historical 9B reports and commits remain audit evidence. The active Ollama 9B tag remains decommissioned. ADR-0009 records the separate llama.cpp runtime, exact artifact identity, and rollback boundary; the 4B/BGE-M3 default remains unchanged.

## Validation

Governance tests protect the 4B/BGE-M3/Codex roles, keep Phase 4 limited to its accepted active models, and require ADR-0009 for any optional advanced-provider references.
