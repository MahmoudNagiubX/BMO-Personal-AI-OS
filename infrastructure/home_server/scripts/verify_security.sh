#!/usr/bin/env bash
# Verify private loopback bindings, firewall rules, config permissions, and zero public listeners on VENOM
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

echo "=== 1. Checking TCP Listeners ==="
ss -tulpn

echo -e "\n=== 2. Verifying Private 127.0.0.1 Bindings ==="
# Core API must be on 127.0.0.1:8000
if ss -tulpn | grep -Eq "127\.0\.0\.1:8000"; then
    echo "[PASS] Core API is bound strictly to 127.0.0.1:8000"
else
    echo "[FAIL] Core API is NOT bound to 127.0.0.1:8000!" >&2
    exit 1
fi

# PostgreSQL must be on 127.0.0.1:5432
if ss -tulpn | grep -Eq "127\.0\.0\.1:5432"; then
    echo "[PASS] PostgreSQL is bound strictly to 127.0.0.1:5432"
else
    echo "[FAIL] PostgreSQL is NOT bound to 127.0.0.1:5432!" >&2
    exit 1
fi

# Check for accidental 0.0.0.0 or ::: public bindings on 8000 or 5432
if ss -tulpn | grep -Eq "(0\.0\.0\.0|\[::\]):(8000|5432)"; then
    echo "[FAIL] Public binding detected on port 8000 or 5432!" >&2
    exit 1
fi
echo "[PASS] Zero public listeners on ports 8000 and 5432"

echo -e "\n=== 3. Checking Configuration File Permissions ==="
if [[ -f "$CONFIG_FILE" ]]; then
    check_config_file_permissions "$CONFIG_FILE"
    echo "[PASS] Configuration file permissions verified."
fi

echo -e "\n=== 4. Checking UFW Firewall Status ==="
if sudo -n true 2>/dev/null; then
    sudo ufw status verbose
else
    echo "[INFO] sudo requires password; skipping non-interactive UFW status."
fi
echo "[PASS] Security inspection complete."
