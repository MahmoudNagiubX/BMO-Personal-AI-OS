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
uv run python scripts/phase_04/benchmark_models.py --base-url http://127.0.0.1:11434 --manifest infrastructure/tuf/model_manifest.json --output $env:TEMP\bmo-phase-04\functional-intermediate.json --replace --allow-pending-restart
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/stop_phase_04_ollama.ps1
```

The bounded restart evidence procedure is part of acceptance and must be run
after the functional benchmark, using the same dedicated roots and pinned
runtime. The first benchmark output is explicitly intermediate because the
runtime is still awaiting the restart gate:

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/start_phase_04_ollama.ps1
uv run python scripts/phase_04/benchmark_models.py `
  --base-url http://127.0.0.1:11434 `
  --manifest infrastructure/tuf/model_manifest.json `
  --output $env:TEMP\bmo-phase-04\functional-intermediate.json `
  --replace --allow-pending-restart
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/stop_phase_04_ollama.ps1

# Restart the same pinned runtime, verify /api/version and /api/tags, then run
# one bounded qwen3.5:4b marker smoke and one bounded bge-m3:567m three-vector
# smoke. Record only the scalar pass/fail, identity, dimension, finite-value,
# and semantic-ordering results in $env:TEMP\bmo-phase-04\restart.json.
# Unload both models, run the dedicated stop script, and verify no LISTEN socket
# or Ollama/llama process remains before merging the scalar object below.

uv run python scripts/phase_04/sanitize_evidence.py `
  --input $env:TEMP\bmo-phase-04\functional-intermediate.json `
  --restart-json $env:TEMP\bmo-phase-04\restart.json `
  --output docs/phase_reports/evidence/PHASE_04_TUF_BENCHMARK.json `
  --replace
```

The restart procedure refuses acceptance unless the first stop released the
listener/process, verifies the same Ollama version and exact active model
inventory after restart, performs bounded Qwen and BGE smokes, checks finite
1,024-dimensional BGE vectors and semantic ordering, then unloads and stops
the dedicated runtime. The final sanitizer changes intermediate acceptance to
pass only when the scalar restart object has `status: pass`; accepted evidence
with missing or pending restart evidence is rejected. The scalar object is
generated only from those verified command results and contains no prompts,
responses, paths, or credentials.

The launcher also updates the user-level `%USERPROFILE%\.ollama\server.json`
to disable cloud access. It backs up the prior file and preserves unrelated
settings. This persistent user configuration is an external side effect:
stopping the dedicated runtime does not restore it automatically, because
another Ollama process may depend on the current setting. Restore the recorded
backup only after confirming that no other Ollama process uses the file.

The benchmark refuses non-loopback URLs, verifies exact digests and model
metadata, permits no concurrent generation request, uses only a synthetic local
vision image, and writes only sanitized scalar evidence. CI runs the unit and
contract portions only; it neither downloads models nor requires CUDA.

## Rollback

Stop the recorded dedicated Ollama PID with the stop script and confirm that
port 11434 is released. The model root may be removed only with owner approval;
the repository has no model binary or database migration to roll back.
