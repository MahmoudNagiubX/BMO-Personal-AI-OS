#!/usr/bin/env bash
# Perform encrypted database backup of PostgreSQL on VENOM
# Usage: ./backup_database.sh [OUTPUT_DIR] [PASSPHRASE_FILE]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

OUTPUT_DIR="${1:-$HOME/venom/backups}"
PASSPHRASE_FILE="${2:-$HOME/venom/config/backup_passphrase.txt}"

echo "=== Starting Encrypted Database Backup ==="

# Load and validate DB credentials (fail closed if missing)
load_database_credentials

# Require independent backup passphrase file (fail closed)
if [[ ! -f "$PASSPHRASE_FILE" ]]; then
    echo "Error: Independent backup passphrase file not found: $PASSPHRASE_FILE" >&2
    echo "Backup encryption material is mandatory and must not fall back to database password." >&2
    exit 1
fi

if [[ ! -s "$PASSPHRASE_FILE" ]]; then
    echo "Error: Backup passphrase file is empty: $PASSPHRASE_FILE" >&2
    exit 1
fi

if command -v chmod >/dev/null 2>&1; then
    chmod 600 "$PASSPHRASE_FILE" 2>/dev/null || true
fi

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
ENC_DUMP="$OUTPUT_DIR/bmo_postgres_${TIMESTAMP}.dump.enc"
SHA_FILE="${ENC_DUMP}.sha256"

# Create secure temporary directory for plaintext dump with restricted umask
OLD_UMASK=$(umask)
umask 077
TEMP_DIR=$(mktemp -d)
umask "$OLD_UMASK"

RAW_DUMP="$TEMP_DIR/bmo_postgres_${TIMESTAMP}.dump"

cleanup() {
    if [[ -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT INT TERM

echo "1. Generating PostgreSQL dump for database $DB_NAME..."
docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$RAW_DUMP"

if [[ ! -s "$RAW_DUMP" ]]; then
    echo "Error: Generated dump file is empty." >&2
    exit 1
fi

echo "2. Encrypting dump with AES-256-CBC using independent key file..."
openssl enc -aes-256-cbc -salt -pbkdf2 -in "$RAW_DUMP" -out "$ENC_DUMP" -pass "file:$PASSPHRASE_FILE"

# Immediately remove plaintext dump
rm -rf "$TEMP_DIR"

# Generate SHA-256 sidecar
echo "3. Generating SHA-256 checksum..."
(cd "$OUTPUT_DIR" && sha256sum "$(basename "$ENC_DUMP")" > "$(basename "$SHA_FILE")")

echo "Encrypted local database backup complete: $ENC_DUMP"
echo "Checksum: $(cat "$SHA_FILE")"
echo "Note: Local backup is stored on VENOM. Off-device replication to backup authority is a separate operational step."
