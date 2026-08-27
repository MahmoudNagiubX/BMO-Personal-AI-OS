# Runbook: Phase 6–8 Persistent Authority Stack Operations on VENOM

## Overview
This runbook documents the operational procedures for deploying, maintaining, upgrading, rolling back, and backing up the BMO Personal AI OS persistent authority stack on VENOM (Lenovo G450).

## 1. Directory & Service Architecture
- **Releases directory**: `/home/venom/venom/core/releases/<commit_sha>`
- **Active release symlink**: `/home/venom/venom/core/current -> /home/venom/venom/core/releases/<active_sha>`
- **Active release venv**: `/home/venom/venom/core/releases/<active_sha>/.venv`
- **Shared venv symlink**: `/home/venom/venom/core/venv -> /home/venom/venom/core/releases/<active_sha>/.venv`
- **Deployed commit record**: `/home/venom/venom/core/deployed-commit`
- **Configuration file**: `/home/venom/venom/config/core.env` (permissions `0600`)
- **Backup passphrase file**: `/home/venom/venom/config/backup_passphrase.txt` (permissions `0600`)
- **PostgreSQL container**: `bmo-postgres` (`pgvector/pgvector:pg16-bookworm`), bound to `127.0.0.1:5432`, volume `bmo_postgres_data`.
- **Systemd user service**: `bmo-core.service` (`~/.config/systemd/user/bmo-core.service`).

## 2. Configuration & Secret Contract
- `core.env` defines canonical environment variables:
  - `BMO_ENVIRONMENT=production`
  - `BMO_DATABASE_URL=postgresql+psycopg://<USER>:<STRONG_PASSWORD>@127.0.0.1:5432/<DBNAME>`
  - Optional explicit matching `BMO_POSTGRES_USER`, `BMO_POSTGRES_PASSWORD`, `BMO_POSTGRES_DB`
  - `BMO_BUILD_SHA=<DEPLOYED_COMMIT_SHA>`
  - `BMO_LOG_LEVEL=INFO`
- **Strict secret policies**:
  - No default database passwords or usernames are permitted.
  - Missing configuration or secrets cause deployment and backup scripts to fail closed before making changes.
  - Secrets are never printed to terminal, logs, or commit records.
  - Configuration and backup passphrase files must be owned by the runtime user where POSIX ownership is
    available and have effective mode no broader than `0600`; remediation is re-statted and failures stop.
  - Backup encryption requires an independent passphrase file (`backup_passphrase.txt`) and never falls back to the database password.

## 3. Standard Operations

### Deploy PostgreSQL
```bash
./infrastructure/home_server/scripts/deploy_postgres.sh
```

### Deploy a Release
```bash
./infrastructure/home_server/scripts/deploy_release.sh <COMMIT_SHA> [MIGRATION_TARGET]
```
Deployment performs:
1. Exact 40-character hexadecimal commit validation.
2. Mandatory verification of release Git metadata, `git rev-parse HEAD`, exact SHA identity,
   and a clean worktree; missing or invalid Git metadata fails closed.
3. Deterministic locked virtualenv creation via `uv sync --frozen --no-dev`.
4. Alembic database migration upgrade.
5. Atomic symlink update, `systemctl --user enable bmo-core`, and service restart with health verification. This keeps the existing user unit enabled across subsequent user-manager starts; it does not change the separately evaluated `Linger` policy.

### Rollback a Release
```bash
./infrastructure/home_server/scripts/rollback_release.sh <TARGET_COMMIT_SHA> <MIGRATION_DOWN_REVISION>
```
Rollback performs:
1. Target commit SHA verification and clean working tree check.
2. Mandatory target Git metadata, exact HEAD, and clean worktree verification.
3. Deterministic target dependency synchronization via `uv sync --frozen --no-dev`.
4. Alembic migration downgrade to target revision.
5. Symlink and configuration update.
6. `systemctl --user enable bmo-core`, service restart, and comprehensive post-rollback verification (readiness, build SHA, database schema,
   PostgreSQL health, and the explicit `/health/model-gateway` readiness contract). A failed model-gateway
   check is a rollback failure; generic liveness or database readiness does not substitute for it.

### Check System Health
```bash
./infrastructure/home_server/scripts/check_health.sh
```

### Encrypted Database Backup
```bash
./infrastructure/home_server/scripts/backup_database.sh [OUTPUT_DIR] [PASSPHRASE_FILE]
```
Performs AES-256-CBC encryption using the independent passphrase file, with secure isolated temporary dump handling and SHA-256 sidecar generation.

### Verify Backup Restoration
```bash
./infrastructure/home_server/scripts/verify_restore.sh <ENC_DUMP_FILE> [PASSPHRASE_FILE]
```
Tests decryption, restore into a temporary database, schema/data validation, and clean teardown.

### Security & Listener Verification
```bash
./infrastructure/home_server/scripts/verify_security.sh
```
Verifies loopback-only bindings (`127.0.0.1:8000`, `127.0.0.1:5432`), configuration file permissions, and UFW status.
