# Phase 1 — Lenovo/VENOM foundation report

**Status:** IN PROGRESS — repository-side foundation ready for independent review

## Scope

This report records the repository-side continuation from `main` at
`09593cc1874d997fb4888db326068112cf0afd7f` on
`phase-01/lenovo-control-plane-foundation`. It incorporates the owner-provided
VENOM physical handoff and adds bounded evidence/runbook tooling. It does not
claim completion of the Lenovo Safety Gate.

## Physical evidence incorporated

The sanitized handoff records:

- VENOM / `venom-server` / Linux user `venom`.
- Lenovo G450, Intel Core 2 Duo T6500, 2 cores, x86_64, approximately 4 GiB
  RAM.
- Ubuntu Server 24.04.4 LTS and `/dev/sda` Seagate ST9320325AS at
  approximately 298 GiB.
- Clean SMART result, passed short test, and zero reallocated, pending, and
  offline-uncorrectable sectors.
- SSH reachability, UFW enabled with SSH allowed, and the manual FastAPI proof
  result `VENOM online / brain initialized`.

The evidence source is the owner-provided
`VENOM_SERVER_FOUNDATION_COMPLETE_HANDOFF`; no new physical or SSH collection
was performed by Codex.

## Repository files

- `docs/phases/PHASE_01_LENOVO_CONTROL_PLANE_FOUNDATION.md`
- `infrastructure/home_server/README.md`
- `infrastructure/home_server/evidence/venom_foundation_handoff.json`
- `infrastructure/home_server/runbooks/01-foundation-inventory.md`
- `infrastructure/home_server/runbooks/02-ssh-firewall.md`
- `infrastructure/home_server/runbooks/03-logs-backup-restore.md`
- `infrastructure/home_server/runbooks/04-reboot-and-stability.md`
- `scripts/phase_01/check_foundation_prerequisites.sh`
- `scripts/phase_01/validate_foundation_evidence.py`
- `tests/unit/phase_01/test_foundation_evidence.py`

Canonical status, master-plan hardware facts, README, and START_HERE wording
are updated in the same change. The manual `~/venom/core/brain` workspace was
not recreated, moved, or extended.

## Physical gate status

**INCOMPLETE.** Ethernet, memory/swap, filesystem/LVM/free-space, thermals and
fans, battery/power, SSH hardening, firewall scope, resource admission, log
rotation, backup/restore, reboot/recovery, and the 24-hour and 7-day stability
gates still require owner-run evidence and review.

## Validation record

Local validation completed on the working tree:

| Command | Result |
|---|---|
| `uv sync --group dev --locked` | Passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run mypy .` | Passed |
| `uv run pytest` | 192 passed, 3 PostgreSQL integration tests skipped because `BMO_TEST_DATABASE_URL` is unset |
| `uv run python scripts/verify_governance.py` | Passed |
| `uv run python scripts/check.py` | Passed; 192 non-integration tests passed and 3 integration tests skipped |
| `uv run pre-commit run --all-files` | Passed |
| `git diff --check` | Passed |

Exact-head GitHub CI remains pending until the branch is pushed. This report
does not claim CI or physical Safety Gate acceptance.

## Safety and phase boundary

No Lenovo SSH session, remote command, physical change, public port, BIOS
change, LVM resize, uncontrolled stress test, production service, model
download, database migration, Phase 5B work, PR merge, or history rewrite was
authorized or performed by this repository task.
