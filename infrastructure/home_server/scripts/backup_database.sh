#!/usr/bin/env bash
# Perform encrypted database backup of PostgreSQL on VENOM
# Usage: ./backup_database.sh [OUTPUT_DIR] [PASSPHRASE_FILE]
set -euo pipefail

OUTPUT_DIR="${1:-$HOME/venom/backups}"
PASSPHRASE_FILE="${2:-$HOME/venom/config/backup_passphrase.txt}"

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
RAW_DUMP="$OUTPUT_DIR/bmo_postgres_${TIMESTAMP}.dump"
ENC_DUMP="${RAW_DUMP}.enc"
SHA_FILE="${ENC_DUMP}.sha256"

if [[ -f "$HOME/venom/config/core.env" ]]; then
    set -a
    source "$HOME/venom/config/core.env"
    set +a
fi

DB_USER="${BMO_DB_USER:-bmo_user}"
DB_NAME="${BMO_DB_NAME:-bmo_personal_ai_os}"

echo "Taking PostgreSQL dump for $DB_NAME..."
docker exec -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$RAW_DUMP"

echo "Encrypting backup with AES-256-CBC..."
if [[ -f "$PASSPHRASE_FILE" ]]; then
    openssl enc -aes-256-cbc -salt -pbkdf2 -in "$RAW_DUMP" -out "$ENC_DUMP" -pass file:"$PASSPHRASE_FILE"
else
    echo "Passphrase file not found, using BMO_DB_PASSWORD as encryption key..."
    openssl enc -aes-256-cbc -salt -pbkdf2 -in "$RAW_DUMP" -out "$ENC_DUMP" -k "${BMO_DB_PASSWORD:-bmo_password}"
fi

# Remove unencrypted dump
rm -f "$RAW_DUMP"

# Generate SHA-256 sidecar
(cd "$OUTPUT_DIR" && sha256sum "$(basename "$ENC_DUMP")" > "$(basename "$SHA_FILE")")

echo "Encrypted backup complete: $ENC_DUMP"
echo "Checksum: $(cat "$SHA_FILE")"
