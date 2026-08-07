# Phase 5A — Software Model Gateway Report

## Acceptance decision

PHASE 5A ACCEPTED locally. The branch remains subject to independent review,
final-head GitHub CI, and owner merge.

## Scope and repository

- Branch: `phase-05a/model-gateway`.
- Base: `a4a4cf78890c5efe98830a6ecc22757cf9f826f2`, the PR #8 merge commit.
- Scope: software-only model gateway contracts and provider integration.
- No Phase 5B, physical deployment, memory/RAG, agents, tools, voice,
  satellites, Qwen3.5 9B, or database migration was started.

## Active models and routing

- Qwen3.5 4B tag: `qwen3.5:4b`.
- Qwen3.5 4B digest:
  `sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`.
- BGE-M3 tag: `bge-m3:567m`.
- BGE-M3 digest:
  `sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
- BGE-M3 dimension: 1,024.
- Qwen3.5 9B: deferred, absent, and non-routable.

Generation, chat, multilingual, structured output, typed tool proposal data,
and explicit-image vision route only to Qwen3.5 4B. Text embeddings route only
to BGE-M3. Invalid capability/modality/model combinations fail before provider
transport.

## Contracts and safety behavior

The BMO-owned contracts cover model identity, capabilities, modalities,
messages, explicit image bytes, structured schemas, declarative tools,
generation responses, embeddings, usage, health, and typed errors. Structured
JSON and tool arguments are validated deterministically with no repair call.
Tool proposals are normalized as data and never executed.

Accepted context tiers are 4,096, 8,192, and 16,384. Output is capped at 256,
and contexts above 4,096 retain the accepted 32-token Phase 4 output cap.
Message count, total text, image count/bytes, embedding batch/text, timeout, and
output limits fail before transport.

Health distinguishes available, degraded, and offline. Exact tag/digest checks
fail closed. Retries are capped at two attempts with bounded backoff. The
in-process circuit breaker has deterministic closed/open/half-open behavior,
and one semaphore preserves one-request-at-a-time inference with typed busy
behavior for a second caller.

## Real TUF gateway smoke

The optional smoke used the existing pinned Phase 4 Ollama 0.32.5 runtime and
did not download or modify a model. It verified:

- health `available` with exact Qwen3.5 4B and BGE-M3 identities;
- one bounded Qwen gateway call with the expected synthetic marker;
- one BGE gateway call with one finite 1,024-dimensional vector;
- after the Phase 4 stop script, health `offline` and generation returned typed
  `provider_unavailable` within the two-attempt bound;
- no cloud fallback, port 11434 listener, Ollama process, or llama process
  remained.

The smoke exposed two adapter representation details and both were fixed at the
provider boundary: Ollama inventory digests are canonicalized from bare SHA-256
to the registry's `sha256:` form before exact comparison, and Qwen reasoning is
explicitly disabled to preserve the accepted Phase 4 interactive profile. No
identity, test, budget, or security check was weakened.

## Tests and validation

The Phase 5A suite adds deterministic coverage for registry/manifest
consistency, exact routing, practical budgets, structured output, tool proposal
data, vision, embeddings, endpoint security, provider normalization, health,
offline/degraded distinction, retries, circuit transitions, concurrency,
request limits, no cloud fallback, and sensitive-content non-logging.

The full local suite passed with 183 tests and three expected PostgreSQL
integration skips because `BMO_TEST_DATABASE_URL` is not set locally. GitHub CI
is authoritative for PostgreSQL readiness, migrations, and the full integrated
validation path.

## Security and data impact

The implementation adds no cloud provider, cloud SDK, API key, arbitrary URL
fetch, public binding, tool execution, prompt/response persistence, vector
persistence, model binary, personal fixture, telemetry, or raw provider-body
leakage. Ollama lifecycle remains owned by Phase 4 scripts. No database schema
or migration changed.

## Boundary

The Phase 5A PR must remain open and unmerged for independent review. After
owner merge, the Desktop Home Server Safety Gate is mandatory. Phase 5B and
physical deployment have not started.
