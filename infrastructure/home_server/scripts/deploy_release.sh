#!/usr/bin/env bash
# Deploy an exact Core API release on VENOM with deterministic dependencies
# Usage: ./deploy_release.sh <COMMIT_SHA> [MIGRATION_TARGET]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <COMMIT_SHA> [MIGRATION_TARGET]" >&2
    exit 1
fi

COMMIT_SHA="$1"
MIGRATION_TARGET="${2:-head}"

# 1. Verify exact release identity (40 lowercase hex, reject traversal / invalid chars)
if ! validate_commit_sha "$COMMIT_SHA"; then
    exit 1
fi

RELEASE_DIR="$HOME/venom/core/releases/$COMMIT_SHA"
CURRENT_LINK="$HOME/venom/core/current"
DEPLOYED_COMMIT_FILE="$HOME/venom/core/deployed-commit"
SHARED_VENV="$HOME/venom/core/venv"

echo "=== Deploying release $COMMIT_SHA (migration: $MIGRATION_TARGET) ==="

# 2. Verify release directory existence and git identity
if [[ ! -d "$RELEASE_DIR" ]]; then
    echo "Error: Release directory not found: $RELEASE_DIR" >&2
    exit 1
fi

if [[ ! -f "$RELEASE_DIR/pyproject.toml" || ! -f "$RELEASE_DIR/uv.lock" ]]; then
    echo "Error: Release directory $RELEASE_DIR missing pyproject.toml or uv.lock" >&2
    exit 1
fi

# Verify git commit matches requested commit exactly
if command -v git >/dev/null 2>&1 && [[ -d "$RELEASE_DIR/.git" || -f "$RELEASE_DIR/.git" ]]; then
    ACTUAL_SHA=$(git -C "$RELEASE_DIR" rev-parse HEAD 2>/dev/null || true)
    if [[ -z "$ACTUAL_SHA" ]]; then
        echo "Error: Failed to determine git HEAD for release directory $RELEASE_DIR" >&2
        exit 1
    fi
    if [[ "$ACTUAL_SHA" != "$COMMIT_SHA" ]]; then
        echo "Error: Release directory HEAD ($ACTUAL_SHA) does not match requested commit ($COMMIT_SHA)" >&2
        exit 1
    fi
    # Verify no uncommitted source mutation
    MUTATIONS=$(git -C "$RELEASE_DIR" status --porcelain 2>/dev/null || true)
    if [[ -n "$MUTATIONS" ]]; then
        echo "Error: Release directory $RELEASE_DIR has uncommitted source mutations:" >&2
        echo "$MUTATIONS" >&2
        exit 1
    fi
fi

# 3. Locate uv and install locked deterministic dependencies into release venv
UV_BIN=$(find_uv_bin)
echo "Installing deterministic locked dependencies via uv into $RELEASE_DIR/.venv..."
(cd "$RELEASE_DIR" && "$UV_BIN" sync --frozen --no-dev)

RELEASE_VENV="$RELEASE_DIR/.venv"
if [[ ! -x "$RELEASE_VENV/bin/alembic" || ! -x "$RELEASE_VENV/bin/uvicorn" ]]; then
    echo "Error: Failed to install required release binaries (alembic, uvicorn) in $RELEASE_VENV" >&2
    exit 1
fi

# 4. Load config and apply Alembic database migrations
echo "Applying Alembic migrations to $MIGRATION_TARGET..."
load_database_credentials

export PYTHONPATH="$RELEASE_DIR/src:$RELEASE_DIR/packages/openjarvis_adapter/src:$RELEASE_DIR"
(cd "$RELEASE_DIR" && "$RELEASE_VENV/bin/alembic" upgrade "$MIGRATION_TARGET")

# 5. Update symlinks and deployed commit metadata
echo "Updating current release symlink..."
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
ln -sfn "$RELEASE_VENV" "$SHARED_VENV"
echo "$COMMIT_SHA" > "$DEPLOYED_COMMIT_FILE"

# Update BMO_BUILD_SHA in config file
if grep -q "^BMO_BUILD_SHA=" "$CONFIG_FILE"; then
    sed -i "s/^BMO_BUILD_SHA=.*/BMO_BUILD_SHA=$COMMIT_SHA/" "$CONFIG_FILE"
else
    echo "BMO_BUILD_SHA=$COMMIT_SHA" >> "$CONFIG_FILE"
fi

# 6. Restart Core API service and verify health
echo "Restarting bmo-core service..."
systemctl --user restart bmo-core
sleep 2

# Verify readiness and version
echo "Verifying Core API readiness..."
READY=0
for i in {1..15}; do
    if curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done

if [[ "$READY" -ne 1 ]]; then
    echo "Error: bmo-core failed health/ready check after restart." >&2
    exit 1
fi

VERSION_OUT=$(curl -fsS http://127.0.0.1:8000/version 2>/dev/null || echo "{}")
echo "Active Core API version: $VERSION_OUT"

echo "Release $COMMIT_SHA successfully deployed and active!"
