#!/usr/bin/env bash
# Rollback Core API release, downgrade Alembic migration, and verify exact target runtime on VENOM
# Usage: ./rollback_release.sh <TARGET_COMMIT_SHA> <MIGRATION_DOWN_REVISION>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <TARGET_COMMIT_SHA> <MIGRATION_DOWN_REVISION>" >&2
    exit 1
fi

TARGET_COMMIT="$1"
TARGET_MIGRATION="$2"

# 1. Verify target commit SHA format
if ! validate_commit_sha "$TARGET_COMMIT"; then
    exit 1
fi

RELEASE_DIR="$HOME/venom/core/releases/$TARGET_COMMIT"
CURRENT_LINK="$HOME/venom/core/current"
DEPLOYED_COMMIT_FILE="$HOME/venom/core/deployed-commit"
SHARED_VENV="$HOME/venom/core/venv"

echo "=== Rolling back to release $TARGET_COMMIT (target migration: $TARGET_MIGRATION) ==="

# 2. Verify target release directory and git identity
if [[ ! -d "$RELEASE_DIR" ]]; then
    echo "Error: Target release directory not found: $RELEASE_DIR" >&2
    exit 1
fi

if [[ ! -f "$RELEASE_DIR/pyproject.toml" || ! -f "$RELEASE_DIR/uv.lock" ]]; then
    echo "Error: Target release directory $RELEASE_DIR missing pyproject.toml or uv.lock" >&2
    exit 1
fi

if command -v git >/dev/null 2>&1 && [[ -d "$RELEASE_DIR/.git" || -f "$RELEASE_DIR/.git" ]]; then
    ACTUAL_SHA=$(git -C "$RELEASE_DIR" rev-parse HEAD 2>/dev/null || true)
    if [[ -z "$ACTUAL_SHA" ]]; then
        echo "Error: Failed to determine git HEAD for release directory $RELEASE_DIR" >&2
        exit 1
    fi
    if [[ "$ACTUAL_SHA" != "$TARGET_COMMIT" ]]; then
        echo "Error: Target release directory HEAD ($ACTUAL_SHA) does not match requested target ($TARGET_COMMIT)" >&2
        exit 1
    fi
    MUTATIONS=$(git -C "$RELEASE_DIR" status --porcelain 2>/dev/null || true)
    if [[ -n "$MUTATIONS" ]]; then
        echo "Error: Target release directory $RELEASE_DIR has uncommitted source mutations:" >&2
        echo "$MUTATIONS" >&2
        exit 1
    fi
fi

# 3. Ensure target release environment is deterministically synced
UV_BIN=$(find_uv_bin)
echo "Restoring target release locked dependencies via uv..."
(cd "$RELEASE_DIR" && "$UV_BIN" sync --frozen --no-dev)

TARGET_VENV="$RELEASE_DIR/.venv"

# 4. Load config and downgrade Alembic migration
echo "Downgrading Alembic migrations to $TARGET_MIGRATION..."
load_database_credentials

# Run migration downgrade using current environment before switching symlink
if [[ -d "$CURRENT_LINK" && -x "$CURRENT_LINK/.venv/bin/alembic" ]]; then
    export PYTHONPATH="$CURRENT_LINK/src:$CURRENT_LINK/packages/openjarvis_adapter/src:$CURRENT_LINK"
    (cd "$CURRENT_LINK" && "$CURRENT_LINK/.venv/bin/alembic" downgrade "$TARGET_MIGRATION")
else
    export PYTHONPATH="$RELEASE_DIR/src:$RELEASE_DIR/packages/openjarvis_adapter/src:$RELEASE_DIR"
    (cd "$RELEASE_DIR" && "$TARGET_VENV/bin/alembic" downgrade "$TARGET_MIGRATION")
fi

# 5. Update symlinks and configuration
echo "Updating symlinks to target release..."
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
ln -sfn "$TARGET_VENV" "$SHARED_VENV"
echo "$TARGET_COMMIT" > "$DEPLOYED_COMMIT_FILE"

if grep -q "^BMO_BUILD_SHA=" "$CONFIG_FILE"; then
    sed -i "s/^BMO_BUILD_SHA=.*/BMO_BUILD_SHA=$TARGET_COMMIT/" "$CONFIG_FILE"
else
    echo "BMO_BUILD_SHA=$TARGET_COMMIT" >> "$CONFIG_FILE"
fi

# 6. Restart Core API service
echo "Restarting bmo-core service..."
systemctl --user restart bmo-core
sleep 2

# 7. Complete Post-Rollback Verification
echo "=== Post-Rollback Verification ==="

# 7.1 Verify Core API readiness
echo "Checking /health/ready..."
READY=0
for i in {1..15}; do
    if curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
if [[ "$READY" -ne 1 ]]; then
    echo "Error: /health/ready failed after rollback!" >&2
    exit 1
fi
echo "[PASS] Core API is healthy and ready."

# 7.2 Verify Build SHA
echo "Checking /version build_sha..."
VERSION_OUT=$(curl -fsS http://127.0.0.1:8000/version 2>/dev/null)
if ! echo "$VERSION_OUT" | grep -q "$TARGET_COMMIT"; then
    echo "Error: /version does not match target commit $TARGET_COMMIT: $VERSION_OUT" >&2
    exit 1
fi
echo "[PASS] /version matches target build SHA: $TARGET_COMMIT"

# 7.3 Verify PostgreSQL health and Alembic revision
echo "Checking PostgreSQL health and migration revision..."
CURRENT_REV=$(docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT version_num FROM alembic_version;" 2>/dev/null || true)
if [[ "$CURRENT_REV" != "$TARGET_MIGRATION" ]]; then
    echo "Error: Alembic revision in PostgreSQL ($CURRENT_REV) does not match target ($TARGET_MIGRATION)" >&2
    exit 1
fi
echo "[PASS] Database migration revision verified: $TARGET_MIGRATION"

# 7.4 Verify Model Gateway probe / health
echo "Checking Model Gateway health..."
if curl -fsS http://127.0.0.1:8000/api/v1/models/health >/dev/null 2>&1 || curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "[PASS] Model Gateway / health routes are active."
fi

echo "Rollback to $TARGET_COMMIT (migration: $TARGET_MIGRATION) successfully completed and verified!"
