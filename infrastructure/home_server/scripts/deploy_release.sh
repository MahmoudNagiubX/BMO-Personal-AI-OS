#!/usr/bin/env bash
# Deploy an exact Core API release on VENOM
# Usage: ./deploy_release.sh <COMMIT_SHA> <MIGRATION_TARGET>
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <COMMIT_SHA> [MIGRATION_TARGET]" >&2
    exit 1
fi

COMMIT_SHA="$1"
MIGRATION_TARGET="${2:-head}"

RELEASE_DIR="$HOME/venom/core/releases/$COMMIT_SHA"
CURRENT_LINK="$HOME/venom/core/current"
CONFIG_FILE="$HOME/venom/config/core.env"
VENV_DIR="$HOME/venom/core/venv"

echo "Deploying release $COMMIT_SHA (migration: $MIGRATION_TARGET)..."

if [[ ! -d "$RELEASE_DIR" ]]; then
    echo "Release directory not found: $RELEASE_DIR" >&2
    exit 1
fi

# Setup Python virtualenv if not present
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating Python virtualenv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Install release dependencies
echo "Installing release dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$RELEASE_DIR"

# Apply Alembic database migrations
echo "Applying Alembic migrations to $MIGRATION_TARGET..."
export PYTHONPATH="$RELEASE_DIR/src:$RELEASE_DIR/packages/openjarvis_adapter/src:$RELEASE_DIR"
set -a
source "$CONFIG_FILE"
set +a
(cd "$RELEASE_DIR" && "$VENV_DIR/bin/alembic" upgrade "$MIGRATION_TARGET")

# Update symlink and metadata
echo "Updating current release symlink..."
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
echo "$COMMIT_SHA" > "$HOME/venom/core/deployed-commit"
sed -i "s/^BMO_BUILD_SHA=.*/BMO_BUILD_SHA=$COMMIT_SHA/" "$CONFIG_FILE"

# Restart Core API service
echo "Restarting bmo-core service..."
systemctl --user restart bmo-core
sleep 2
systemctl --user is-active bmo-core

echo "Release $COMMIT_SHA successfully deployed and active!"
