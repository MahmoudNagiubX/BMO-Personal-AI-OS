# Phase 2 Report - Core Platform Skeleton

## Scope

Phase 2 establishes the health-only modular-monolith platform boundary on the ASUS development branch. No agent behavior, model integration, tools, authentication, device control, voice, memory, or Lenovo deployment was added.

## Components

- FastAPI application factory with liveness, readiness, and version routes.
- Typed `BMO_` environment settings with production development-URL protection.
- Standard-library JSON logging and request correlation-ID middleware.
- SQLAlchemy 2 declarative metadata, lazy engine factory, session factory, and `SELECT 1` health check.
- Alembic baseline that enables `vector` idempotently and defines no product tables.
- Local PostgreSQL/pgvector Compose service and GitHub Actions PostgreSQL service.

## Closeout implementation

The original CI wait step passed a SQLAlchemy URL directly to `psycopg.connect()`, so CI failed before migrations and integration tests with `missing "=" after ... in connection info string`; PostgreSQL itself was healthy. The workflow now uses SQLAlchemy `create_engine()` with the application URL, `SELECT 1`, bounded retries, engine disposal, and one concise timeout error. The workflow also pins uv `0.12.1`, uses `persist-credentials: false`, binds the service to `127.0.0.1`, and runs integration tests once through `scripts/check.py`.

The application lifespan disposes the lazy SQLAlchemy engine on shutdown. Database configuration now accepts only `postgresql+psycopg://` URLs, with focused rejection tests for `postgresql://`, `postgres://`, and SQLite URLs. The integration and endpoint tests retain their existing behavior and cover the lifecycle change.

## Dependencies

Runtime dependencies are FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy 2, Alembic, and Psycopg 3 with its binary development package. HTTPX was added to the development group for endpoint tests. No dependencies or lockfile entries changed in this closeout.

## Endpoint contracts

- `GET /health/live` returns HTTP 200 and `{"status":"ok"}` without a database call.
- `GET /health/ready` runs the replaceable bounded database health function, returning HTTP 200 with `{"status":"ready"}` or HTTP 503 with the generic `database unavailable` detail.
- `GET /version` returns project name, package version, and configured build SHA only.

Unit tests cover all three endpoints, readiness replacement and failure redaction, and absence of product endpoints.

## Configuration, logging, and correlation

Settings use the `BMO_` prefix, `.env` locally, and a safe `unknown` build-SHA default. The JSON formatter emits UTC timestamp, level, logger, message, correlation ID, and bounded request fields. It excludes arbitrary log extras and redacts sensitive key/value message patterns. Correlation IDs accept only the bounded header allowlist, are returned on responses, and are reset after normal and exceptional requests.

## Database and migration evidence

`compose.dev.yml` uses `pgvector/pgvector:pg16-bookworm`, a maintained image documented by the pgvector project, with one named-volume PostgreSQL service and a `127.0.0.1`-only published port. The migration revision is `20260803_0001` (`enable pgvector extension`) and contains only the idempotent extension operation with an empty-schema downgrade.

On CI run `30788348713`, the service became healthy, SQLAlchemy readiness passed, Alembic applied `20260803_0001`, `alembic current` reported the head, and `alembic check` reported no new upgrade operations. The real integration test confirmed the `vector` extension, confirmed the migration head, and confirmed database-backed readiness.

## Validation evidence

PR #4 (`https://github.com/MahmoudNagiubX/BMO-Personal-AI-OS/pull/4`) passed workflow `CI` run `30788348713` with job `91606445935` on Python 3.12 and uv `0.12.1`. The single `scripts/check.py` validation run executed all 30 tests exactly once: 27 non-integration tests and 3 PostgreSQL integration tests passed. Ruff lint, Ruff formatting, strict Mypy, governance and secret guard, migration validation, and the integration path all passed. The run completed with one Starlette/httpx deprecation warning; no test failed.

Local checks were constrained by the environment: project-dependent commands using the managed Python 3.12 runtime failed before execution because an Application Control policy blocked `_socket`, and the Docker daemon was unavailable. Local `uv lock --check`, `git diff --check`, Compose configuration, syntax compilation, no-project Ruff checks, and governance validation passed. GitHub CI is the authoritative Python 3.12/PostgreSQL result for this closeout.

## Security result

No high or blocker findings were identified. CI permissions remain `contents: read`; checkout uses `persist-credentials: false`; local and CI PostgreSQL publishing is localhost-only; no production credentials, `.env` file, telemetry, or personal data were added; database URLs are not logged; readiness errors are generic; and no public application binding was introduced.

## Phase state and sequencing

Phase 2 technical acceptance criteria are satisfied on PR #4; owner merge remains pending. Phase 1 remains incomplete and parked at `phase-01/lenovo-foundation` commit `d160302f146c1954b4a2e4e797f078e618a60f21`. Phase 3 remains unstarted. After Phase 3, coding must stop and return to the Lenovo physical safety gate before Phase 4; Phase 4 is not authorized by this report.

## Next step

Independent repository review and owner merge decision. Do not begin Phase 3 in this task.
