# Phase 3 — OpenJarvis Compatibility Evidence

## Scope and sequencing

This report records the bounded Phase 3 compatibility spike on
`phase-03/openjarvis-compatibility-spike`. The existing Phase 3 implementation
commit was preserved and not amended, reset, rebased, squashed, or discarded.
Phase 1 remains parked and unchanged. Phase 4, model installation, Lenovo work,
and production agent integration remain unauthorized.

Local implementation and focused validation are complete. The identifier-
hardening implementation passed GitHub Python 3.12 / PostgreSQL CI on PR #5;
documentation-head CI and independent review remain pending. Phase 3 technical
acceptance criteria are satisfied on PR #5; owner merge remains pending.

## Upstream and artifact verification

- Official repository: [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
- Release tag: `v1.0.0`
- Approved source commit: `e97088f199cf86ea5f78de921772357d1f0d2cec`
- Official PyPI distribution: `OpenJarvis`, normalized by tooling as `openjarvis`
- Exact release: `1.0.0`
- Repository link in PyPI metadata: `https://github.com/open-jarvis/OpenJarvis`
- Python requirement: `>=3.10`, including Python 3.12
- License: Apache-2.0
- Upload timestamps: wheel `2026-05-16T20:48:15.971119Z`; sdist `2026-05-16T20:48:19.396815Z`
- Trusted Publishing status: not reported in the official PyPI JSON response.

Official PyPI JSON metadata and file URLs were retrieved from the pinned
`OpenJarvis/1.0.0` release. Both artifacts were downloaded to a temporary
directory outside the repository and verified locally:

| Artifact | Filename | SHA-256 | Result |
|---|---|---|---|
| Wheel | `openjarvis-1.0.0-py3-none-any.whl` | `5d56bf50e556f2eb6612cb49e844557e10a083094e527cb59f03fd257f3dc7d4` | Matches PyPI |
| Source distribution | `openjarvis-1.0.0.tar.gz` | `1673d5160a5574bee789d4f0528239fc85e5f45ba0b5093c1c34024183ddcb44` | Matches PyPI |

The approved GitHub commit archive was separately downloaded and extracted.
The normal VCS dependency was not used because that release contains the
`Inline` gitlink without the required `.gitmodules` metadata. No upstream
metadata was repaired, and no source was forked, vendored, or modified.

## Release/source comparison

After normalizing only archive-root prefixes and line endings, the wheel,
sdist, and approved GitHub archive contained 612 common Python files with zero
content mismatches. The four Git-only files are the `openjarvis.traces`
package files; they are not imported or accessed by this adapter.

The adapter’s actual import path was exercised with the PyPI wheel. The relied-
upon files below were each SHA-256 equivalent across wheel, sdist, and the
approved GitHub archive:

| Upstream file | SHA-256 |
|---|---|
| `src/openjarvis/__init__.py` | `10e07ab5702bf6002f95f9856ac6c12e6f3c160f09c4f091808f28deee007b63` |
| `src/openjarvis/core/types.py` | `4fbb732ae4daae5b117ecb37cc1f270cc67a614e51a1e5d37b7fbcbaabd66011` |
| `src/openjarvis/core/events.py` | `bc07143994d6161bdb846c587a66bca9b58d129b1f66c5aa3686fae2298c4637` |
| `src/openjarvis/core/registry.py` | `a311c97995ba4bd1b5fecaf917d9727f3d94790e9f2309f3c7b914a61810d226` |
| `src/openjarvis/engine/_base.py` | `dad11f51af2ef54d2a6a9b53c47894ee68613a0deae39f6b6c743ccc0ef59b6d` |
| `src/openjarvis/engine/_openai_compat.py` | `af4836acad3009f358c2ea3f89fae0f5605045877d817e012d233c070ffc0b13` |
| `src/openjarvis/engine/_stubs.py` | `ae72e43e44dd0156cc387b2c31965d7a3213a615c9792234479b76319a77406b` |
| `src/openjarvis/engine/openai_compat_engines.py` | `a6c98339bf66e975e1a2f2bbd5d06b9a7bb444afd0b28d8a856e19273c81b489` |
| `src/openjarvis/tools/_stubs.py` | `aa2ae314597ab70339af5dedb7ff8032a545044ca51e550d4c12af2bd52b7d06` |

The sdist `pyproject.toml` is byte-equivalent to the approved GitHub archive’s
`pyproject.toml`. Wheel metadata reports `Name: OpenJarvis`, `Version: 1.0.0`,
`License: Apache-2.0`, `Requires-Python: >=3.10`, and the official repository.

## Dependency correction

Old dependency form:

```text
openjarvis @ git+https://github.com/open-jarvis/OpenJarvis.git@e97088f199cf86ea5f78de921772357d1f0d2cec
```

New dependency form:

```text
openjarvis==1.0.0
```

`uv.lock` now records the official PyPI registry source, exact version, wheel
and sdist URLs, hashes, sizes, and upload times. No Git source, local path,
fork, vendored source, or unrelated dependency upgrade remains.

## Adapter architecture

- Package path: `packages/openjarvis_adapter/src/bmo_openjarvis_adapter/`
- Product-owned contracts: `LocalModelRequest`, `LocalModelResponse`, `Usage`,
  `ToolDefinition`, `OpenJarvisToolSchema`, `TraceEvent`, and
  `OpenJarvisAdapterError`.
- Direct upstream imports are confined to `upstream.py`; the AST boundary test
  rejects equivalent imports elsewhere.
- Actual upstream APIs: `VLLMEngine`, `Message`, `Role`, and `ToolSpec`.
- The adapter exposes no raw OpenJarvis objects, endpoint, agent loop, model
  loader, cloud fallback, tool callable, shell, database persistence, or UI.

## Identifier and trace hardening

- `request_id` and `trace_id` accept only `^[A-Za-z0-9._-]{1,128}$`.
- `model_id` accepts only `^[A-Za-z0-9._/:-]{1,128}$`, preserving namespaced
  and Ollama-style tags such as `local/qwen3.5:9b`.
- Trace scalar values remain allowlisted and bounded, while rejecting bearer or
  basic credentials, key/token/secret/password assignments, database URLs,
  Windows and common Unix user paths, control characters, and meaningful
  `sk-`-prefixed token bodies.
- Rejected identifiers and values are not echoed in validation or translation
  errors. Focused tests cover accepted and rejected request/model/trace IDs,
  safe-key redaction, and preservation of ordinary safe values.

## Compatibility proof

The project’s locked Python 3.12 environment installed the official PyPI
wheel. Contract tests exercised the real OpenJarvis request path through
`VLLMEngine`, using a `127.0.0.1` HTTP server bound to an ephemeral port.

- Synthetic input: `Return exactly: BMO_OPENJARVIS_SPIKE_OK`
- Expected and returned text: `BMO_OPENJARVIS_SPIKE_OK`
- Request model, messages, temperature, and token bound were verified at the
  loopback server.
- No API key, cloud provider, external test traffic, or model download was
  required.
- `get_demo_status` translated into the real declarative `ToolSpec` shape;
  no callable was registered or executed.
- Unsupported schema features and extra arguments fail safely.
- Trace translation preserves bounded safe fields and redacts secret-like
  values, paths, request bodies, and arbitrary objects.
- Network isolation rejects non-loopback providers and the test socket guard
  fails any non-loopback connection.
- Compatibility artifact generation writes only to a test temporary directory;
  no generated report is committed.

## Analytics and telemetry

OpenJarvis v1.0.0 contains local telemetry and trace-storage layers, but the
adapter uses the direct local engine API and does not construct the SDK,
`InstrumentedEngine`, `TelemetryStore`, or `TraceStore`. The inspected release
contains no external analytics endpoint used by this path. The adapter adds no
analytics dependency, upload, monitoring provider, or cloud fallback; its
analytics state is explicitly false and covered by contract tests.

## Validation

| Command | Result |
|---|---|
| `uv --version` | Exit 0 — uv 0.11.29 |
| `uv run python --version` | Exit 0 — Python 3.12.13 |
| `uv lock --check` | Exit 0 |
| `uv sync --group dev --locked` | Exit 0 |
| `uv run ruff check .` | Exit 0 |
| `uv run ruff format --check .` | Exit 0 — 61 files formatted |
| `uv run python -m mypy` | Exit 0 — 24 source files, no issues |
| `uv run pytest` | Exit 0 — 57 passed, 3 skipped, 1 warning |
| `uv run pytest tests/contract -v` | Exit 0 — 6 passed |
| `uv run python scripts/verify_governance.py` | Exit 0 |
| `uv run python scripts/check.py` | Exit 0 — working invocation; 57 non-integration tests selected locally |
| `uv run python -m pre_commit run --all-files` | Exit 0 — Ruff, formatting, governance passed |
| `git diff --check` | Exit 0 |
| `docker info` | Exit 1 — Docker daemon unavailable |

The final local suite collected 60 tests. The three skipped tests are PostgreSQL
integration tests because `BMO_TEST_DATABASE_URL` was not set. The only warning
was the existing Starlette/httpx deprecation warning. Direct executable-path
Mypy and pre-commit invocations remain subject to Windows Application Control;
the supported module invocations and `scripts/check.py` passed.

## GitHub CI evidence

The initial accepted branch CI was run `30794890370`, job `91626113992`, on
head `e64ca70aa080162d82b5997ecd48d7128286891a`, with 44 tests passed,
including 6 OpenJarvis contract tests and 3 PostgreSQL integration tests.

The identifier-hardening implementation CI passed as run `30795588483`, job
`91628309151`, on head
`435e3439dccf364101934f85a604373b9691a9f9`:

- Python 3.12.3 and pinned uv 0.12.1;
- healthy PostgreSQL/pgvector service bound to `127.0.0.1:5432`;
- Alembic upgrade/current/check passed at `20260803_0001`;
- vector extension integration test passed;
- 60 tests passed, including 6 OpenJarvis contract tests and 3 PostgreSQL
  integration tests;
- Ruff, formatting, Mypy, governance, and secret guard passed;
- one existing Starlette/httpx deprecation warning.

The documentation-head CI run is intentionally not claimed until this evidence
commit is pushed.

## Security review

No Blocker, High, Medium, or Low security findings were identified.

- No secrets, credentials, personal data, or downloaded artifacts are tracked.
- No analytics traffic, PostHog transmission, external trace upload, or cloud
  fallback exists.
- Contract traffic is limited to the loopback ephemeral test server.
- Unsafe request, model, and trace identifiers are rejected before entering
  product-owned trace records; credential/path-like values under safe keys are
  redacted without echoing their contents.
- No public binding, shell, tool execution, endpoint, migration, or database
  schema change was added.
- No direct OpenJarvis import exists outside the adapter package.
- No Phase 1, Lenovo, or Phase 4 work was performed.

## Rollback and deferral

Rollback the Phase 3 PR by reverting its merge commit. This removes the pinned
OpenJarvis dependency, adapter package, contract tests, and Phase 3 evidence
while preserving the previously merged Phase 2 API/database foundation.
No database rollback is required because Phase 3 adds no migration.

## Dependency footprint limitation

Official OpenJarvis 1.0.0 brings a broad base dependency set. No model is
downloaded or loaded, Lenovo deployment is not authorized, and runtime
footprint and Lenovo suitability remain subject to the later hardware and
deployment gate.

After Phase 3 merge, coding must pause for the mandatory Lenovo physical safety
gate; Phase 4 remains unauthorized.
