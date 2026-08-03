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

## Pinned runtime

- Version: `v0.32.5`
- Official source: `https://github.com/ollama/ollama/releases/tag/v0.32.5`
- Release commit prefix: `eec8e0b`
- Archive: `ollama-windows-amd64.zip`
- Official archive SHA-256: pending verified release download
- Executable SHA-256: pending verified release download
- Authenticode: collected during verified installation

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

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/start_phase_04_ollama.ps1
Invoke-RestMethod http://127.0.0.1:11434/api/version
Invoke-RestMethod http://127.0.0.1:11434/api/tags
powershell -ExecutionPolicy Bypass -File infrastructure/tuf/stop_phase_04_ollama.ps1
```

No sign-in, cloud model, API key, public binding, firewall change, Docker
runtime, WSL runtime, Windows service, or startup task is part of Phase 4.

## Rollback

Stop only the recorded dedicated PID with `stop_phase_04_ollama.ps1` and verify
that port `11434` is free. Preserve the timestamped server-config backup and
restore it only when no other Ollama process depends on it. Removing the
dedicated runtime is non-destructive to the repository; removing the dedicated
model root requires explicit owner confirmation because it contains large
downloaded artifacts. Unrelated Ollama installations and models are never
removed. Phase 4 adds no database migration, so no database rollback is needed.

## Scope status

This is the Commit 1 runtime-boundary skeleton. Exact archive and executable
hashes, model tags/digests, measured benchmark evidence, and acceptance status
are populated only after the official runtime and locked models pass the local
Phase 4 gates.
