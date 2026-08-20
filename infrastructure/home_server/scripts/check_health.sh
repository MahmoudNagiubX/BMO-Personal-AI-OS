#!/usr/bin/env bash
# Check VENOM host resources, PostgreSQL, Core API health, and version
set -euo pipefail

echo "=== 1. VENOM Host Resources ==="
free -h
df -h /
sensors 2>/dev/null || true

echo -e "
=== 2. PostgreSQL Status ==="
if docker ps --format '{{.Names}}' | grep -Eq "^bmo-postgres$"; then
    echo "bmo-postgres container is running."
else
    echo "bmo-postgres container is NOT running!" >&2
fi

echo -e "
=== 3. Core API Service Status ==="
systemctl --user status bmo-core --no-pager

echo -e "
=== 4. Core API Ready Check ==="
curl -s http://127.0.0.1:8000/health/ready
echo ""

echo -e "
=== 5. Core API Version Check ==="
curl -s http://127.0.0.1:8000/version
echo ""
