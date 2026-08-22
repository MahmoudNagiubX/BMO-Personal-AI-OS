# Phase 9 Windows satellite

This directory defines the bounded per-user Windows satellite. It opens one
authenticated outbound WebSocket to the VENOM Core API and never creates a TUF
listener, firewall rule, administrator service, general shell, or remote
desktop surface.

## Local configuration

Copy `allowlist.template.json` to a path outside Git and replace only the fixed
stable IDs and absolute local targets that the owner has reviewed. Unknown
fields, duplicate IDs, relative paths, environment expansion, UNC paths,
caller-supplied arguments, and targets absent at startup are rejected.

Create a non-secret JSON file outside Git with this shape:

```json
{
  "endpoint": "wss://venom.example.invalid/api/v1/satellites/windows/connect",
  "allowlist_path": "C:\\Users\\owner\\AppData\\Local\\BMO\\WindowsSatellite\\allowlist.json",
  "state_root": "C:\\Users\\owner\\AppData\\Local\\BMO\\WindowsSatellite"
}
```

Production requires `wss://`; plaintext `ws://` is accepted only for a
loopback development endpoint. The reusable device credential is stored only
in Windows Credential Manager under the fixed product target and is never
placed in this JSON, the task arguments, environment variables, logs, or Git.

## Enrollment and lifecycle

After the owner creates a short-lived, single-use Phase 6 enrollment with the
`satellite.connect`, heartbeat, capability-report, and required Phase 8 tool
scopes, redeem it interactively:

```powershell
uv run python scripts/phase_09/enroll_windows_satellite.py
powershell -ExecutionPolicy RemoteSigned -File infrastructure/tuf/windows_satellite/install_satellite_task.ps1 -RepositoryRoot $PWD -ConfigPath $configPath
powershell -ExecutionPolicy RemoteSigned -File infrastructure/tuf/windows_satellite/manage_satellite.ps1 -Action Start
```

The task runs only in the current user's interactive session at limited
privilege and restarts at most three times after a failure. Status, restart,
and stop use the same script with `-Action Status`, `Restart`, or `Stop`.

Credential rotation atomically replaces the secure-store value:

```powershell
uv run python scripts/phase_09/rotate_windows_satellite_credential.py
```

## Rollback

Stop and remove only the product-owned task:

```powershell
powershell -ExecutionPolicy RemoteSigned -File infrastructure/tuf/windows_satellite/manage_satellite.ps1 -Action Remove
```

Removal preserves the secure credential so an accidental task rollback does
not destroy device identity. Explicit credential deletion is a separate owner
action via `scripts/phase_09/remove_windows_satellite_credential.py`. Local
allowlist, logs, and replay metadata contain no reusable credential and remain
available for review until the owner removes them.
