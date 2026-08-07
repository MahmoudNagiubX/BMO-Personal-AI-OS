# Phase 5A — Software-only model gateway

## Goal

Provide a small, typed, deterministic, fail-closed BMO model gateway for the
accepted local Qwen3.5 4B and BGE-M3 stack. This phase defines software
contracts only; it does not deploy the gateway or expose the TUF over a
network.

## Architecture

The dependency direction is product code to
`personal_ai_os.model_gateway`, then its narrow provider protocol, then the
Ollama adapter. Product contracts never expose Ollama JSON or provider
exceptions. The gateway is independent of OpenJarvis internals and preserves
the existing OpenJarvis import boundary.

The canonical gateway registry contains exactly:

- `qwen3.5:4b` as the local-only primary model, with the Phase 4 digest,
  generation, chat, multilingual, structured-output, tool-proposal, and vision
  capabilities;
- `bge-m3:567m` as the local-only embeddings model, with the Phase 4 digest and
  1,024-dimensional output.

Qwen3.5 9B is deferred and has no registry or routing entry. A contract test
compares the gateway registry with `infrastructure/tuf/model_manifest.json` so
the accepted tags and digests cannot drift silently.

## Contracts and routing

Generation requests contain a bounded request identifier, typed messages,
explicit image bytes when vision is requested, optional bounded structured
schema or tool definitions, practical context tier, output budget, and timeout.
Responses contain the exact model identity, normalized text or validated
structured/tool-proposal data, bounded usage, finish reason, and latency. Tool
proposals are data only and the gateway has no execution callback.

Embedding requests support one bounded text or a small batch. Responses must
have exactly one finite 1,024-dimensional vector per input. The gateway does
not chunk, persist, retrieve, or write pgvector data.

Routing is exact:

- generation, chat, multilingual, structured output, and tool proposals with
  text route to Qwen3.5 4B;
- explicit text plus image vision routes to Qwen3.5 4B;
- text embeddings route to BGE-M3.

Unsupported modalities, unknown capabilities, cross-role requests, and 9B
requests fail before transport. Practical context tiers are 4,096, 8,192, and
16,384 tokens. Output is capped at 256 tokens, with the accepted Phase 4
32-token cap for contexts above 4,096.

## Resilience and availability

Health uses only provider version and inventory calls. It reports `available`
when the pinned provider and both exact model identities are present,
`degraded` when the provider is reachable but version/model identity is wrong
or missing, and `offline` when the provider cannot be reached. TUF model state
does not control global backend liveness.

Defaults are a 2-second health timeout, 60-second generation timeout, 30-second
embedding timeout, at most two total attempts, 50-millisecond bounded retry
backoff, two transient failures to open the circuit, and a 30-second cooldown.
The in-process circuit uses a monotonic clock and deterministic
closed/open/half-open behavior. Validation, unsupported requests, identity
mismatch, structured-output failure, and deterministic provider rejection are
not retried and do not count as transient circuit failures.

One bounded semaphore permits one inference request at a time. A second caller
waits at most 100 milliseconds by default, then receives a typed `busy` error.

## Security and privacy

The default endpoint is `http://127.0.0.1:11434`. Endpoint validation rejects
unspecified/public addresses, hostnames, credentials, paths, unsupported
schemes, and cloud URLs. A future private IP requires an explicit deployment
setting; Phase 5A does not configure one.

The adapter exposes only version, inventory, chat, and embedding operations. It
cannot pull, install, update, delete, start, or stop models. Images are supplied
as bytes; the gateway fetches no URL. It stores and logs no prompt, response,
image, vector, tool argument, secret, or raw provider payload. There is no cloud
provider, cloud SDK, API key, analytics, or fallback.

## Acceptance and rollback

CI-safe tests use deterministic providers and require no Ollama, GPU, internet,
or model download. Optional real smoke may use the already accepted Phase 4
runtime and must end with typed offline behavior plus no listener/process.

This phase adds no database migration. Rollback is a normal revert of the Phase
5A code, tests, and documentation. No runtime model or database state is owned
by the gateway.

After owner merge, stop product coding for the Desktop Home Server Safety Gate.
Phase 5B, physical deployment, and Phase 6 are not authorized by this phase.
