#!/usr/bin/env bash
# Check VENOM host resources, PostgreSQL, Core API health, and version
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

echo "=== 1. VENOM Host Resources ==="
free -h
df -h /
sensors 2>/dev/null || true

echo -e "\n=== 2. PostgreSQL Status ==="
if docker ps --format '{{.Names}}' | grep -Eq "^bmo-postgres$"; then
    echo "[PASS] bmo-postgres container is running."
    if [[ -f "$CONFIG_FILE" ]]; then
        load_database_credentials
        if docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres pg_isready -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
            echo "[PASS] PostgreSQL is responding to queries on 127.0.0.1:5432."
        else
            echo "[WARN] PostgreSQL container running but pg_isready failed."
        fi
    fi
else
    echo "[FAIL] bmo-postgres container is NOT running!" >&2
    exit 1
fi

echo -e "\n=== 3. Core API Service Status ==="
systemctl --user status bmo-core --no-pager

echo -e "\n=== 4. Core API Ready Check ==="
curl -fsS http://127.0.0.1:8000/health/ready
echo ""

echo -e "\n=== 5. Core API Version Check ==="
curl -fsS http://127.0.0.1:8000/version
echo ""
