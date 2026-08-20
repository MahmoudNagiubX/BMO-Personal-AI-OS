#!/usr/bin/env bash
# Rollback Core API release and downgrade Alembic migration on VENOM
# Usage: ./rollback_release.sh <TARGET_COMMIT_SHA> <MIGRATION_DOWN_REVISION>
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <TARGET_COMMIT_SHA> <MIGRATION_DOWN_REVISION>" >&2
    exit 1
fi

TARGET_COMMIT="$1"
TARGET_MIGRATION="$2"

RELEASE_DIR="$HOME/venom/core/releases/$TARGET_COMMIT"
CURRENT_LINK="$HOME/venom/core/current"
CONFIG_FILE="$HOME/venom/config/core.env"
VENV_DIR="$HOME/venom/core/venv"

echo "Rolling back to release $TARGET_COMMIT (migration: $TARGET_MIGRATION)..."

if [[ ! -d "$RELEASE_DIR" ]]; then
    echo "Target release directory not found: $RELEASE_DIR" >&2
    exit 1
fi

# Downgrade Alembic migrations from current
export PYTHONPATH="$CURRENT_LINK/src:$CURRENT_LINK/packages/openjarvis_adapter/src:$CURRENT_LINK"
set -a
source "$CONFIG_FILE"
set +a
(cd "$CURRENT_LINK" && "$VENV_DIR/bin/alembic" downgrade "$TARGET_MIGRATION")

# Update symlink and configuration
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
echo "$TARGET_COMMIT" > "$HOME/venom/core/deployed-commit"
sed -i "s/^BMO_BUILD_SHA=.*/BMO_BUILD_SHA=$TARGET_COMMIT/" "$CONFIG_FILE"

# Restart Core API service
systemctl --user restart bmo-core
sleep 2
systemctl --user is-active bmo-core

echo "Rollback to $TARGET_COMMIT complete!"
