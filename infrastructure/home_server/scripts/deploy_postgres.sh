#!/usr/bin/env bash
# Deploy persistent private PostgreSQL/pgvector container on VENOM
set -euo pipefail

CONTAINER_NAME="bmo-postgres"
DATA_VOLUME="bmo_postgres_data"
IMAGE="pgvector/pgvector:pg16-bookworm"

echo "Deploying PostgreSQL/pgvector on VENOM..."

# Ensure data volume exists
if ! docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1; then
    echo "Creating Docker volume: $DATA_VOLUME"
    docker volume create "$DATA_VOLUME"
fi

# Source database credentials from config if available
if [[ -f "$HOME/venom/config/core.env" ]]; then
    set -a
    source "$HOME/venom/config/core.env"
    set +a
fi

DB_USER="${BMO_DB_USER:-bmo_user}"
DB_PASS="${BMO_DB_PASSWORD:-bmo_password}"
DB_NAME="${BMO_DB_NAME:-bmo_personal_ai_os}"

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
        "$IMAGE"
fi

# Await readiness
echo "Waiting for PostgreSQL readiness..."
for i in {1..30}; do
    if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        echo "PostgreSQL is ready!"
        exit 0
    fi
    sleep 1
done

echo "PostgreSQL failed to become ready in time." >&2
exit 1
