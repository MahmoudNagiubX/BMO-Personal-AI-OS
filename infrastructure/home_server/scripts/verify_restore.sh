#!/usr/bin/env bash
# Verify encrypted backup restoration into a temporary PostgreSQL database on VENOM
# Usage: ./verify_restore.sh <ENC_DUMP_FILE> [PASSPHRASE_FILE]
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <ENC_DUMP_FILE> [PASSPHRASE_FILE]" >&2
    exit 1
fi

ENC_DUMP="$1"
PASSPHRASE_FILE="${2:-$HOME/venom/config/backup_passphrase.txt}"
TEMP_DIR=$(mktemp -d)
TEMP_DUMP="$TEMP_DIR/restore_test.dump"
TEMP_DB="bmo_restore_test"

trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ -f "$HOME/venom/config/core.env" ]]; then
    set -a
    source "$HOME/venom/config/core.env"
    set +a
fi

DB_USER="${BMO_DB_USER:-bmo_user}"

echo "1. Verifying SHA-256 checksum..."
DIRNAME=$(dirname "$ENC_DUMP")
BASENAME=$(basename "$ENC_DUMP")
if [[ -f "$ENC_DUMP.sha256" ]]; then
    (cd "$DIRNAME" && sha256sum -c "$BASENAME.sha256")
fi

echo "2. Decrypting backup file..."
if [[ -f "$PASSPHRASE_FILE" ]]; then
    openssl enc -d -aes-256-cbc -pbkdf2 -in "$ENC_DUMP" -out "$TEMP_DUMP" -pass file:"$PASSPHRASE_FILE"
else
    openssl enc -d -aes-256-cbc -pbkdf2 -in "$ENC_DUMP" -out "$TEMP_DUMP" -k "${BMO_DB_PASSWORD:-bmo_password}"
fi

echo "3. Creating temporary database $TEMP_DB..."
docker exec -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres dropdb -U "$DB_USER" --if-exists "$TEMP_DB"
docker exec -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres createdb -U "$DB_USER" "$TEMP_DB"

echo "4. Restoring dump into $TEMP_DB..."
docker exec -i -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres pg_restore -U "$DB_USER" -d "$TEMP_DB" < "$TEMP_DUMP"

echo "5. Verifying schema and table row counts..."
docker exec -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres psql -U "$DB_USER" -d "$TEMP_DB" -c "SELECT version_num FROM alembic_version;"
docker exec -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres psql -U "$DB_USER" -d "$TEMP_DB" -c "SELECT count(*) AS owners_count FROM owners;"

echo "6. Dropping temporary database $TEMP_DB..."
docker exec -e PGPASSWORD="${BMO_DB_PASSWORD:-bmo_password}" bmo-postgres dropdb -U "$DB_USER" "$TEMP_DB"

echo "Backup verification PASSED: dump is decryptable and restorable without errors!"
