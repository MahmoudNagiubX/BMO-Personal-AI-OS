# Phase 4 — ASUS TUF Model Node Report

## Acceptance decision

PHASE 4 ACCEPTED locally. The branch remains subject to independent review,
final-head GitHub CI, and owner merge.

## Scope and repository

- Branch: `phase-04/tuf-model-node`.
- Base: `caeb366af121ed3f2dca5239f34346a13f8a031a` (PR #7 merge).
- The historical local Phase 4 commits were preserved and current `main` was
  integrated with a normal merge. No rebase, amend, squash, force-push, or
  history rewrite was used.
- Evidence: `docs/phase_reports/evidence/PHASE_04_TUF_BENCHMARK.json`.

## Hardware and runtime

- Owner-reported device class: ASUS TUF F15, 16 GB RAM.
- Detected with `nvidia-smi`: NVIDIA GeForce RTX 4050 Laptop GPU, 6,141 MiB
  VRAM.
- Windows runtime: Ollama `0.32.5`, official
  `ollama-windows-amd64.zip`, release commit
  `eec8e0b9458b8a01be0c216a9cc53eefde24ef50`.
- Archive SHA-256:
  `7c941ae084569d298062d29f8139163a3187c76dbca0479c70d085e78fd8c7bb`.
- Executable SHA-256:
  `82e3b496c059720fa1c40a09af7803778f4bb40f32fb459a1d799c822a217843`.
- Authenticode: `Valid`, signer `Ollama Inc.`.
- Dedicated process profile: `127.0.0.1:11434`, cloud disabled, one request
  and one loaded model, Flash Attention, q8_0 KV cache, 512 MiB GPU overhead,
  and zero keep-alive.

## Qwen3.5 4B

- Tag: `qwen3.5:4b`.
- Digest: `sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`.
- Size: 3,389,983,735 bytes.
- Official upstream/license: `Qwen/Qwen3.5-4B`, Apache-2.0.
- English, Arabic, mixed Arabic-English, schema-constrained JSON, typed
  tool-call proposal data, and synthetic-image vision all passed. Typed data
  had zero tool executions.
- Practical context passed at 4,096, 8,192, and 16,384. The three-request
  stability sequence passed with start intervals of 32.438 s and 32.031 s.
- Cold load was 7.770827 s; median warm first content was 8.342565 s; median
  generation rate was 53.464023 tokens/s.
- Stability peak: 71 C, peak VRAM: 5,449 MiB, peak power: 75.95 W. No thermal
  warning, throttle, runner crash, HTTP 500, driver reset, or BSOD occurred.

## BGE-M3

- Tag: `bge-m3:567m`.
- Digest: `sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
- Size: 1,157,672,605 bytes.
- Official upstream/license: `BAAI/bge-m3`, MIT.
- Six-vector batch, repeat, finite numeric values, and 1,024 dimensions passed.
- English similarity: 0.839210 similar versus 0.438437 unrelated.
- Arabic similarity: 0.826884 similar versus 0.453296 unrelated.
- Near-limit input passed; intentionally oversized input was rejected with a
  controlled HTTP 400 and the runtime remained usable.
- After stop/restart, BGE returned finite 1,024-dimensional vectors and Arabic
  similarity was 0.967389 versus 0.727648 unrelated.

## Lifecycle and privacy

The runtime completed start, health, exact inventory, Qwen unload, BGE unload,
stop, listener/process verification, restart, representative Qwen/BGE smoke,
and final clean stop. The final state has no listener on port 11434 and no
Ollama or llama runner.

All test traffic was loopback-only. No cloud fallback, telemetry, model binary,
credential, personal fixture, unrestricted shell, or model-triggered action
execution was added. Evidence is sanitized before commit and stores no raw
prompts, model responses, paths, or credentials.

## 9B status and limitations

Qwen3.5 9B is deferred, not active, not restored/downloaded, and not required
by the manifest, scripts, tests, CI, or Phase 4 acceptance. Historical
investigation remains preserved in earlier local commits and ADR-0006.

The initial evidence-writing attempt exposed a sanitizer false positive for the
harmless `power_draw_w` metric. The rule was tightened to reject `raw` as a
field segment, retaining raw-output protection, and the final full acceptance
run passed. A command-channel timeout did not terminate the bounded local
runner; no model failure was observed.

## Validation and next boundary

The final branch must run the canonical repository checks and receive green
GitHub CI before merge. Phase 5A has not started. It becomes eligible only
after independent review and owner merge of the Phase 4 PR.
