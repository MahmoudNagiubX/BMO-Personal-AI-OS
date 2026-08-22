#!/usr/bin/env bash
# Verify encrypted backup restoration into a temporary PostgreSQL database on VENOM
# Usage: ./verify_restore.sh <ENC_DUMP_FILE> [PASSPHRASE_FILE]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <ENC_DUMP_FILE> [PASSPHRASE_FILE]" >&2
    exit 1
fi

ENC_DUMP="$1"
PASSPHRASE_FILE="${2:-$HOME/venom/config/backup_passphrase.txt}"

if [[ ! -f "$ENC_DUMP" ]]; then
    echo "Error: Encrypted dump file not found: $ENC_DUMP" >&2
    exit 1
fi

# Load DB credentials
load_database_credentials

# Require independent backup passphrase file (fail closed)
if [[ ! -f "$PASSPHRASE_FILE" ]]; then
    echo "Error: Backup passphrase file not found: $PASSPHRASE_FILE" >&2
    echo "Backup decryption material is mandatory and must not fall back to database password." >&2
    exit 1
fi

if [[ ! -s "$PASSPHRASE_FILE" ]]; then
    echo "Error: Backup passphrase file is empty: $PASSPHRASE_FILE" >&2
    exit 1
fi

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
TEMP_DB="bmo_restore_test_${TIMESTAMP}"

# Create secure temporary directory for decrypted dump with restricted umask
OLD_UMASK=$(umask)
umask 077
TEMP_DIR=$(mktemp -d)
umask "$OLD_UMASK"

TEMP_DUMP="$TEMP_DIR/restore_test.dump"

# Trap cleanup
cleanup() {
    rm -rf "$TEMP_DIR"
    docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres dropdb -U "$DB_USER" --if-exists "$TEMP_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "1. Verifying SHA-256 checksum..."
DIRNAME=$(dirname "$ENC_DUMP")
BASENAME=$(basename "$ENC_DUMP")
if [[ -f "$ENC_DUMP.sha256" ]]; then
    (cd "$DIRNAME" && sha256sum -c "$BASENAME.sha256")
fi

echo "2. Decrypting backup file using independent key..."
openssl enc -d -aes-256-cbc -pbkdf2 -in "$ENC_DUMP" -out "$TEMP_DUMP" -pass "file:$PASSPHRASE_FILE"

if [[ ! -s "$TEMP_DUMP" ]]; then
    echo "Error: Decrypted dump file is empty." >&2
    exit 1
fi

echo "3. Creating temporary database $TEMP_DB..."
docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres dropdb -U "$DB_USER" --if-exists "$TEMP_DB"
docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres createdb -U "$DB_USER" "$TEMP_DB"

echo "4. Restoring dump into $TEMP_DB..."
docker exec -i -e PGPASSWORD="$DB_PASS" bmo-postgres pg_restore -U "$DB_USER" -d "$TEMP_DB" < "$TEMP_DUMP"

echo "5. Verifying schema and table row counts..."
docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres psql -U "$DB_USER" -d "$TEMP_DB" -c "SELECT version_num FROM alembic_version;"
docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres psql -U "$DB_USER" -d "$TEMP_DB" -c "SELECT count(*) AS owners_count FROM owners;"

echo "6. Dropping temporary database $TEMP_DB..."
docker exec -e PGPASSWORD="$DB_PASS" bmo-postgres dropdb -U "$DB_USER" "$TEMP_DB"

# Explicit cleanup of temp dir
rm -rf "$TEMP_DIR"

echo "Backup verification PASSED: dump is decryptable and restorable without errors!"
