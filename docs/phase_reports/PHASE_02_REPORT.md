# Phase 2 Report — Core Platform Skeleton

## Scope

Phase 2 establishes the health-only modular-monolith platform boundary on the ASUS development branch. No agent behavior, model integration, tools, authentication, device control, voice, memory, or Lenovo deployment was added.

## Components

- FastAPI application factory with liveness, readiness, and version routes.
- Typed `BMO_` environment settings with production development-URL protection.
- Standard-library JSON logging and request correlation-ID middleware.
- SQLAlchemy 2 declarative metadata, lazy engine factory, session factory, and `SELECT 1` health check.
- Alembic baseline that enables `vector` idempotently and defines no product tables.
- Local PostgreSQL/pgvector Compose service and GitHub Actions PostgreSQL service.

## Dependencies

Runtime dependencies are FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy 2, Alembic, and Psycopg 3 with its binary development package. HTTPX was added to the development group for endpoint tests. The lockfile was regenerated with bounded version ranges.

## Endpoint contracts

- `GET /health/live` returns HTTP 200 and `{"status":"ok"}` without a database call.
- `GET /health/ready` runs the replaceable bounded database health function, returning HTTP 200 with `{"status":"ready"}` or HTTP 503 with the generic `database unavailable` detail.
- `GET /version` returns project name, package version, and configured build SHA only.

Unit tests cover all three endpoints, readiness replacement and failure redaction, and absence of product endpoints.

## Configuration, logging, and correlation

Settings use the `BMO_` prefix, `.env` locally, and a safe `unknown` build-SHA default. The JSON formatter emits UTC timestamp, level, logger, message, correlation ID, and bounded request fields. It excludes arbitrary log extras and redacts sensitive key/value message patterns. Correlation IDs accept only the bounded header allowlist, are returned on responses, and are reset after normal and exceptional requests.

## Database and migration evidence

`compose.dev.yml` uses `pgvector/pgvector:pg16-bookworm`, a maintained image documented by the pgvector project, with one named-volume PostgreSQL service and a `127.0.0.1`-only published port. The migration revision is `20260803_0001` (`enable pgvector extension`) and contains only the idempotent extension operation with an empty-schema downgrade.

The local Docker daemon was unavailable during this run, so local migration and real PostgreSQL integration commands were not executed. GitHub Actions provides the required PostgreSQL/pgvector service, migration commands, and real integration tests.

## Validation evidence

Under the available alternate Python 3.14 runtime, Ruff lint, Ruff format, strict Mypy, and the full test suite passed: 23 tests passed and 3 PostgreSQL integration tests skipped because `BMO_TEST_DATABASE_URL` was absent. The mandated Python 3.12 runtime could not execute locally because the machine application-control policy blocked its `_socket` extension; the project remains pinned to Python 3.12 and CI uses Python 3.12.

## Security result

No high or blocker findings were identified in the implementation. Local database publishing is localhost-only, CI permissions remain `contents: read`, no production credentials or `.env` file were added, readiness errors are generic, and logs do not include request bodies or sensitive headers.

## Limitations and sequencing

Phase 1 remains incomplete and parked at `phase-01/lenovo-foundation` commit `d160302f146c1954b4a2e4e797f078e618a60f21`. The owner-approved Phase 2 coding-only exception does not authorize Lenovo deployment. After the separate Phase 3 macro step, coding must stop and return to the Lenovo physical safety gate before Phase 4.

## Next step

Independent repository review and GitHub CI acceptance are required before owner review. Do not begin Phase 3 in this task.
