#!/usr/bin/env bash
# Common configuration and validation utilities for VENOM home server scripts
# Strict security policy: fail closed, zero default passwords, no secret printing

set -euo pipefail

# Configuration file location
DEFAULT_CONFIG_FILE="$HOME/venom/config/core.env"
CONFIG_FILE="${BMO_CONFIG_FILE:-$DEFAULT_CONFIG_FILE}"

# Forbidden default / weak passwords
FORBIDDEN_PASSWORDS=(
    "bmo_password"
    "bmo_dev_only"
    "bmo_ci_only"
    "password"
    "postgres"
    "admin"
    "root"
    "123456"
    "secret"
)

# Immutable PostgreSQL image baseline (pinned exact content digest)
DEFAULT_POSTGRES_IMAGE="pgvector/pgvector:pg16-bookworm@sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b"
POSTGRES_IMAGE="${BMO_POSTGRES_IMAGE:-$DEFAULT_POSTGRES_IMAGE}"

# Verify secret / configuration file exists, is owned by the runtime user, and has mode <= 0600
check_config_file_permissions() {
    local cfg="$1"
    if [[ ! -f "$cfg" ]]; then
        echo "Error: Required secret file not found: $cfg" >&2
        return 1
    fi

    if ! command -v stat >/dev/null 2>&1; then
        echo "Error: 'stat' is required to verify secret file permissions: $cfg" >&2
        return 1
    fi

    local os_type
    os_type=$(uname -s 2>/dev/null || echo "Unknown")

    # Verify owner on Linux / Unix systems when a privileged operator has
    # explicitly supplied the intended non-root runtime UID. Outside sudo,
    # mode 0600 plus the OS read check is the enforceable ownership boundary.
    if [[ ("$os_type" == "Linux" || "$os_type" == "Darwin") && -n "${SUDO_UID:-}" ]]; then
        local file_uid
        file_uid=$(stat -c "%u" "$cfg" 2>/dev/null || stat -f "%u" "$cfg" 2>/dev/null || true)
        local runtime_uid="$SUDO_UID"
        if [[ -z "$file_uid" || -z "$runtime_uid" ]]; then
            echo "Error: Unable to establish the owner of secret file $cfg" >&2
            return 1
        fi
        if [[ "$file_uid" -ne "$runtime_uid" ]]; then
            echo "Error: Secret file $cfg is owned by UID $file_uid, but current runtime user is UID $runtime_uid" >&2
            return 1
        fi
    fi

    # Check and enforce permissions mode <= 0600 (group=0, other=0). The
    # post-remediation stat is mandatory; chmod failures never get ignored.
    local perms
    perms=$(stat -c "%a" "$cfg" 2>/dev/null || stat -f "%Lp" "$cfg" 2>/dev/null || true)
    if [[ -z "$perms" || ! "$perms" =~ ^[0-7]+$ || ${#perms} -lt 2 ]]; then
        echo "Error: Unable to establish secure permissions for secret file $cfg" >&2
        return 1
    fi
    if [[ "${perms: -2}" != "00" ]]; then
        echo "Warning: Secret file $cfg has broad permissions ($perms). Restricting to 600..." >&2
        if ! command -v chmod >/dev/null 2>&1; then
            echo "Error: 'chmod' is required to restrict secret file $cfg" >&2
            return 1
        fi
        if ! chmod 600 "$cfg" 2>/dev/null; then
            echo "Error: Failed to restrict secret file $cfg to 0600" >&2
            return 1
        fi
        local new_perms
        new_perms=$(stat -c "%a" "$cfg" 2>/dev/null || stat -f "%Lp" "$cfg" 2>/dev/null || true)
        if [[ -z "$new_perms" || ! "$new_perms" =~ ^[0-7]+$ || ${#new_perms} -lt 2 || "${new_perms: -2}" != "00" ]]; then
            echo "Error: Secret file $cfg has insecure permissions after remediation" >&2
            return 1
        fi
    fi
    return 0
}

# Verify that a release has an exact, resolvable, clean Git identity.
verify_release_identity() {
    local release_dir="$1"
    local expected_sha="$2"

    if [[ ! -d "$release_dir/.git" && ! -f "$release_dir/.git" ]]; then
        echo "Error: Mandatory Git metadata (.git) not found in release directory $release_dir" >&2
        return 1
    fi
    if ! command -v git >/dev/null 2>&1; then
        echo "Error: 'git' command is required for release identity verification" >&2
        return 1
    fi

    local actual_sha
    actual_sha=$(git -c safe.directory=* -C "$release_dir" rev-parse HEAD 2>/dev/null || true)
    if [[ -z "$actual_sha" || ! "$actual_sha" =~ ^[0-9a-f]{40}$ ]]; then
        echo "Error: Failed to determine a valid Git HEAD for release directory $release_dir" >&2
        return 1
    fi
    if [[ "$actual_sha" != "$expected_sha" ]]; then
        echo "Error: Release directory HEAD ($actual_sha) does not match requested commit ($expected_sha)" >&2
        return 1
    fi

    local mutations
    mutations=$(git -c safe.directory=* -C "$release_dir" status --porcelain --untracked-files=all 2>/dev/null || true)
    if [[ -n "$mutations" ]]; then
        echo "Error: Release directory $release_dir has uncommitted source mutations:" >&2
        echo "$mutations" >&2
        return 1
    fi
    return 0
}

# Verify model-gateway readiness using the target release's own contract.
# New releases expose /health/model-gateway; the accepted historical baseline
# predates that route and must be checked with its own Phase 5B scalar probe.
verify_model_gateway_rollback() {
    local target_release="$1"
    local target_python="$target_release/.venv/bin/python"
    local route_source="$target_release/src/personal_ai_os/api/routes/health.py"

    if [[ ! -x "$target_python" ]]; then
        echo "Error: Target release Python environment is missing: $target_python" >&2
        return 1
    fi

    if [[ -f "$route_source" ]] && grep -Fq '@router.get("/health/model-gateway"' "$route_source"; then
        local response status body
        if ! response=$(curl -sS --max-time 5 -w $'\n%{http_code}' \
            http://127.0.0.1:8000/health/model-gateway 2>/dev/null); then
            echo "Error: Explicit model-gateway readiness request failed" >&2
            return 1
        fi
        status="${response##*$'\n'}"
        body="${response%$'\n'*}"
        if [[ "$status" != "200" ]]; then
            echo "Error: Explicit model-gateway readiness returned HTTP $status" >&2
            return 1
        fi
        if ! printf '%s' "$body" | "$target_python" -c \
            'import json,sys; value=json.load(sys.stdin); raise SystemExit(0 if isinstance(value,dict) and set(value)=={"status"} and value.get("status")=="ready" else 1)'; then
            echo "Error: Explicit model-gateway readiness response is malformed or not ready" >&2
            return 1
        fi
        echo "[PASS] Explicit model-gateway readiness contract is active."
        return 0
    fi

    local probe="$target_release/scripts/phase_05b/probe_gateway.py"
    local observation
    if [[ ! -f "$probe" ]]; then
        echo "Error: Target release model-gateway probe is missing: $probe" >&2
        return 1
    fi
    if ! observation=$("$target_python" "$probe" 2>/dev/null); then
        echo "Error: Target release model-gateway probe failed" >&2
        return 1
    fi
    if ! printf '%s' "$observation" | "$target_python" -c \
        'import json,sys; value=json.load(sys.stdin); booleans=("provider_version_match","qwen_identity_match","bge_identity_match","tunnel_listener_present"); raise SystemExit(0 if isinstance(value,dict) and value.get("gateway_availability")=="available" and all(value.get(key) is True for key in booleans) else 1)'; then
        echo "Error: Target release model-gateway probe reported an unavailable or invalid gateway" >&2
        return 1
    fi
    echo "[PASS] Historical Phase 5B model-gateway probe passed."
}

# Parse database URL or explicit BMO_POSTGRES_* credentials
load_database_credentials() {
    local cfg="${1:-$CONFIG_FILE}"
    if ! check_config_file_permissions "$cfg"; then
        exit 1
    fi

    # Source config securely
    set -a
    # shellcheck disable=SC1090
    source "$cfg"
    set +a

    local raw_url="${BMO_DATABASE_URL:-}"
    local user="${BMO_POSTGRES_USER:-}"
    local pass="${BMO_POSTGRES_PASSWORD:-}"
    local db="${BMO_POSTGRES_DB:-}"
    local host="${BMO_POSTGRES_HOST:-127.0.0.1}"
    local port="${BMO_POSTGRES_PORT:-5432}"

    if [[ -n "$raw_url" ]]; then
        local proto_stripped="${raw_url#*://}"
        local user_pass="${proto_stripped%%@*}"
        local host_port_db="${proto_stripped#*@}"

        local parsed_user="${user_pass%%:*}"
        local parsed_pass="${user_pass#*:}"
        local host_port="${host_port_db%%/*}"
        local parsed_db="${host_port_db#*/}"
        parsed_db="${parsed_db%%\?*}"

        local parsed_host="${host_port%%:*}"
        local parsed_port="${host_port#*:}"
        if [[ "$parsed_port" == "$parsed_host" ]]; then
            parsed_port="5432"
        fi

        if [[ -n "$user" && "$user" != "$parsed_user" ]]; then
            echo "Error: BMO_POSTGRES_USER ($user) does not match BMO_DATABASE_URL user ($parsed_user)" >&2
            exit 1
        fi
        if [[ -n "$pass" && "$pass" != "$parsed_pass" ]]; then
            echo "Error: BMO_POSTGRES_PASSWORD does not match BMO_DATABASE_URL password" >&2
            exit 1
        fi
        if [[ -n "$db" && "$db" != "$parsed_db" ]]; then
            echo "Error: BMO_POSTGRES_DB ($db) does not match BMO_DATABASE_URL database name ($parsed_db)" >&2
            exit 1
        fi

        user="$parsed_user"
        pass="$parsed_pass"
        db="$parsed_db"
        host="$parsed_host"
        port="$parsed_port"
    fi

    if [[ -z "$user" ]]; then
        echo "Error: Database username is missing (set BMO_DATABASE_URL or BMO_POSTGRES_USER in $cfg)" >&2
        exit 1
    fi
    if [[ -z "$pass" ]]; then
        echo "Error: Database password is missing (set BMO_DATABASE_URL or BMO_POSTGRES_PASSWORD in $cfg)" >&2
        exit 1
    fi
    if [[ -z "$db" ]]; then
        echo "Error: Database name is missing (set BMO_DATABASE_URL or BMO_POSTGRES_DB in $cfg)" >&2
        exit 1
    fi

    local pass_lower
    pass_lower=$(echo "$pass" | tr '[:upper:]' '[:lower:]')
    for forbidden in "${FORBIDDEN_PASSWORDS[@]}"; do
        if [[ "$pass_lower" == "$forbidden" ]]; then
            echo "Error: Insecure default or weak database password detected. Production database must use a strong unique secret." >&2
            exit 1
        fi
    done

    if [[ "$host" != "127.0.0.1" && "$host" != "localhost" ]]; then
        echo "Error: Database host must be 127.0.0.1 or localhost (got: $host)" >&2
        exit 1
    fi

    DB_USER="$user"
    DB_PASS="$pass"
    DB_NAME="$db"
    DB_HOST="$host"
    DB_PORT="$port"
}

# Verify commit SHA format (40 lowercase hex)
validate_commit_sha() {
    local sha="$1"
    if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
        echo "Error: Invalid commit SHA '$sha'. Must be exactly 40 lowercase hexadecimal characters." >&2
        return 1
    fi
    return 0
}

# Locate uv executable
find_uv_bin() {
    if command -v uv >/dev/null 2>&1; then
        echo "uv"
    elif [[ -x "$HOME/.local/bin/uv" ]]; then
        echo "$HOME/.local/bin/uv"
    elif [[ -x "$HOME/.cargo/bin/uv" ]]; then
        echo "$HOME/.cargo/bin/uv"
    elif [[ -x "/root/.local/bin/uv" ]]; then
        echo "/root/.local/bin/uv"
    elif [[ -x "/root/.cargo/bin/uv" ]]; then
        echo "/root/.cargo/bin/uv"
    else
        echo "Error: 'uv' executable not found in PATH, ~/.local/bin/uv, or ~/.cargo/bin/uv" >&2
        return 1
    fi
}
