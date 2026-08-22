#!/usr/bin/env bash
# Deploy persistent private PostgreSQL/pgvector container on VENOM
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common_config.sh
source "$SCRIPT_DIR/common_config.sh"

CONTAINER_NAME="bmo-postgres"
DATA_VOLUME="bmo_postgres_data"

echo "=== Deploying PostgreSQL/pgvector on VENOM ==="

# Load and validate credentials (fail closed if missing or insecure)
load_database_credentials

# Ensure data volume exists
if ! docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1; then
    echo "Creating Docker volume: $DATA_VOLUME"
    docker volume create "$DATA_VOLUME"
fi

if docker ps -a --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
    echo "Container $CONTAINER_NAME already exists."
    if ! docker ps --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}$"; then
        echo "Starting existing container $CONTAINER_NAME..."
        docker start "$CONTAINER_NAME"
    fi
else
    echo "Running new $CONTAINER_NAME container bound strictly to 127.0.0.1:5432..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        -p 127.0.0.1:5432:5432 \
        -e POSTGRES_USER="$DB_USER" \
        -e POSTGRES_PASSWORD="$DB_PASS" \
        -e POSTGRES_DB="$DB_NAME" \
        -v "$DATA_VOLUME":/var/lib/postgresql/data \
        "$POSTGRES_IMAGE"
fi

# Await readiness
echo "Waiting for PostgreSQL readiness on 127.0.0.1:5432..."
READY=0
for i in {1..30}; do
    if docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER_NAME" pg_isready -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done

if [[ "$READY" -eq 1 ]]; then
    echo "PostgreSQL is ready and healthy on database $DB_NAME."
    exit 0
else
    echo "Error: PostgreSQL failed to become ready within 30 seconds." >&2
    exit 1
fi
