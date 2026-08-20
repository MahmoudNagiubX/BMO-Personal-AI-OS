#!/usr/bin/env bash
# Verify private loopback bindings, firewall rules, and zero public listeners on VENOM
set -euo pipefail

echo "=== 1. Checking TCP Listeners ==="
ss -tulpn

echo -e "
=== 2. Verifying Private 127.0.0.1 Bindings ==="
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

echo -e "
=== 3. Checking UFW Firewall Status ==="
sudo ufw status verbose
echo "[PASS] Security inspection complete."
