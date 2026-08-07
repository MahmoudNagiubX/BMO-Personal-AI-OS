# Phase 4 — ASUS TUF model node

## Goal

Provide a reproducible, local-only ASUS TUF inference foundation for the
accepted initial model stack: Qwen3.5 4B for generation and BGE-M3 for
embeddings. Qwen3.5 9B is deferred by ADR-0006.

## Scope

- Pinned Ollama Windows runtime with a loopback-only listener.
- Exact active-model manifest, lifecycle scripts, local acceptance runner, and
  CI-safe contract tests.
- Bounded real local tests for multilingual generation, structured output,
  typed tool-call proposal data without execution, synthetic-image vision,
  practical context, embeddings, lifecycle, restart, and thermals.

## Forbidden scope

No model gateway, routing service, persistent model registry, deployment to the
desktop server, action execution, cloud fallback, firewall change, 9B recovery,
or Phase 5A implementation.

## Runtime profile

- Ollama `0.32.5`, official `ollama-windows-amd64.zip` release artifact.
- Process-scoped `127.0.0.1:11434` binding only.
- Conservative CUDA profile: one parallel request, one loaded model, q8_0 KV
  cache, Flash Attention, 512 MiB GPU overhead, and zero keep-alive.
- Models and binaries remain outside Git under the dedicated local runtime and
  model roots.

## Acceptance commands

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/start_phase_04_ollama.ps1
uv run python scripts/phase_04/benchmark_models.py --base-url http://127.0.0.1:11434 --manifest infrastructure/tuf/model_manifest.json --output docs/phase_reports/evidence/PHASE_04_TUF_BENCHMARK.json --replace
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/stop_phase_04_ollama.ps1
```

The benchmark refuses non-loopback URLs, verifies exact digests and model
metadata, permits no concurrent generation request, uses only a synthetic local
vision image, and writes only sanitized scalar evidence. CI runs the unit and
contract portions only; it neither downloads models nor requires CUDA.

## Rollback

Stop the recorded dedicated Ollama PID with the stop script and confirm that
port 11434 is released. The model root may be removed only with owner approval;
the repository has no model binary or database migration to roll back.
