# ASUS TUF Phase 4 local model node

This directory defines the bounded, local-only Ollama runtime boundary for the
ASUS TUF compute plane. It does not create a Windows service, startup task,
firewall rule, LAN listener, product API endpoint, model gateway, or Lenovo
deployment.

## Dedicated locations

The scripts use process-scoped defaults based on these placeholders:

```text
Runtime root: %LOCALAPPDATA%\BMO\Ollama\v0.32.5
Model root:   %LOCALAPPDATA%\BMO\Ollama\models
Evidence:     %TEMP%\bmo-phase-04
```

Model weights and runtime binaries remain outside the repository. Do not change
a persistent `OLLAMA_MODELS` user variable.

## Accepted Phase 4 runtime

- Version: `v0.32.5`
- Official source: `https://github.com/ollama/ollama/releases/tag/v0.32.5`
- Release commit prefix: `eec8e0b`
- Archive: `ollama-windows-amd64.zip`
- Official archive SHA-256: `7c941ae084569d298062d29f8139163a3187c76dbca0479c70d085e78fd8c7bb`
- Executable SHA-256: `82e3b496c059720fa1c40a09af7803778f4bb40f32fb459a1d799c822a217843`
- Authenticode: `Valid`, signer `Ollama Inc.`

The archive, checksum file, executable, and extracted runtime are never
committed. `scripts/phase_04/verify_release.py` validates the official API
metadata, checksum, archive paths, executable version, and Authenticode status
before the runtime can be used.

## Local-only launch

The launcher sets these variables only in its child process:

```text
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_MODELS=%LOCALAPPDATA%\BMO\Ollama\models
OLLAMA_NO_CLOUD=1
```

It refuses an inherited non-empty `OLLAMA_API_KEY`, merges
`%USERPROFILE%\.ollama\server.json` with `disable_ollama_cloud: true`, backs up
an existing configuration outside the repository, checks the listener is
loopback-only, and records only the dedicated child PID in temporary evidence.
The server configuration is user-level and persistent: unrelated settings are
preserved, the backup is retained for owner-controlled rollback, and stopping
the dedicated runtime does not restore the file automatically if another
Ollama process could depend on it.

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/start_phase_04_ollama.ps1
Invoke-RestMethod http://127.0.0.1:11434/api/version
Invoke-RestMethod http://127.0.0.1:11434/api/tags
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/stop_phase_04_ollama.ps1
```

No sign-in, cloud model, API key, public binding, firewall change, Docker
runtime, WSL runtime, Windows service, or startup task is part of Phase 4.

## Accepted models

The active Phase 4 manifest contains only these models:

- `qwen3.5:4b`: primary local generation, conversation, structured-output,
  typed tool-proposal, and vision model; digest
  `sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`.
- `bge-m3:567m`: embeddings model; digest
  `sha256:7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.

Qwen3.5 9B is deferred under ADR-0006. It is not started, downloaded,
required, or benchmarked by the active scripts, tests, or CI.

Run the local-only acceptance suite after the launcher is healthy:

```powershell
uv run python scripts/phase_04/benchmark_models.py `
  --base-url http://127.0.0.1:11434 `
  --manifest infrastructure/tuf/model_manifest.json `
  --output docs/phase_reports/evidence/PHASE_04_TUF_BENCHMARK.json --replace
```

For the required restart gate, write intermediate functional evidence with
`--allow-pending-restart`, stop the runtime, start the same pinned runtime,
verify version/inventory, perform bounded Qwen/BGE smokes, unload both models,
stop again, and verify no process or `LISTEN` socket remains. Record only the
validated scalar restart results and merge them with
`sanitize_evidence.py --restart-json`. The final sanitizer rejects accepted
evidence unless `restart.status` is `pass`.

The runner uses one request at a time, `think: false`, zero keep-alive,
temperature-aware cooldown, a local synthetic vision image, and no tool
execution. The committed evidence is sanitized and contains no raw prompts,
responses, paths, credentials, or model binaries.

## Rollback

Stop only the recorded dedicated PID with `stop_phase_04_ollama.ps1` and verify
that port `11434` is free. Preserve the timestamped server-config backup and
restore it only when no other Ollama process depends on it. Removing the
dedicated runtime is non-destructive to the repository; removing the dedicated
model root requires explicit owner confirmation because it contains large
downloaded artifacts. Unrelated Ollama installations and models are never
removed. Phase 4 adds no database migration, so no database rollback is needed.

## Scope status

Phase 4 acceptance evidence is recorded in
`docs/phase_reports/PHASE_04_REPORT.md` and its sanitized JSON companion.
