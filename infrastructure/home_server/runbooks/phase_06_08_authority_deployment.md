# Runbook: Phase 6–8 Persistent Authority Stack Operations on VENOM

## Overview
This runbook documents the operational procedures for deploying, maintaining, upgrading, rolling back, and backing up the BMO Personal AI OS persistent authority stack on VENOM (Lenovo G450).

## 1. Directory & Service Architecture
- **Releases directory**: /home/venom/venom/core/releases/<commit_sha>
- **Active release symlink**: /home/venom/venom/core/current -> /home/venom/venom/core/releases/<active_sha>
- **Deployed commit record**: /home/venom/venom/core/deployed-commit
- **Configuration file**: /home/venom/venom/config/core.env
- **PostgreSQL container**: mo-postgres (pgvector/pgvector:pg16-bookworm), bound to 127.0.0.1:5432, volume mo_postgres_data.
- **Systemd user service**: mo-core.service (~/.config/systemd/user/bmo-core.service).

## 2. Standard Operations

### Deploy PostgreSQL
`ash
./infrastructure/home_server/scripts/deploy_postgres.sh
`

### Deploy a Release
`ash
./infrastructure/home_server/scripts/deploy_release.sh <COMMIT_SHA> [MIGRATION_TARGET]
`

### Rollback a Release
`ash
./infrastructure/home_server/scripts/rollback_release.sh <TARGET_COMMIT_SHA> <MIGRATION_DOWN_REVISION>
`

### Check System Health
`ash
./infrastructure/home_server/scripts/check_health.sh
`

### Encrypted Database Backup
`ash
./infrastructure/home_server/scripts/backup_database.sh [OUTPUT_DIR] [PASSPHRASE_FILE]
`

### Verify Backup Restoration
`ash
./infrastructure/home_server/scripts/verify_restore.sh <ENC_DUMP_FILE> [PASSPHRASE_FILE]
`

### Security & Listener Verification
`ash
./infrastructure/home_server/scripts/verify_security.sh
`
