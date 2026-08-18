# Phase 1 — VENOM physical safety gate report

**Status:** WAITING_FOR_24H — immediate privileged closeout and reboot
recovery passed; the official 24-hour and 7-day stability windows are now
running.

## Scope completed

This report records the authorized physical-gate session from current `main`
at `a02d08a5012938b165e5e26c88708cda9f1bff9e` on
`phase-01/venom-physical-safety-gate`. It preserves the ASUS TUF → GitHub →
reviewed commit → Lenovo SSH workflow, does not reuse the historical Lenovo
branch, and does not begin Phase 5B.

## Completion mode

The immediate privileged closeout completion mode passed. SMART tooling and
health checks, SSH hardening, scoped UFW, bounded journald policy, durable root
monitoring, encrypted off-device backup and temporary restore proof, and one
controlled reboot with recovery verification all passed. The new official
stability marker is real-time and not backdated. The phase cannot claim final
PASS until 24 continuous hours and then 7 continuous days have elapsed.

## Server identity and access

- Runtime: VENOM; hostname: `venom-server`; Linux user: `venom`.
- Hardware: Lenovo G450; Ubuntu Server 24.04.4 LTS AMD64; x86_64; 2 CPU cores;
  approximately 4 GiB RAM.
- Dedicated Ed25519 key login passed from the ASUS TUF.
- Key fingerprint: `SHA256:fAvEE4TUpb4P524E/We6LRsVG9xygEeXT+mL8r/G1Gg`.
- Password login remains enabled as recovery fallback.
- Root SSH is denied; effective `PermitRootLogin no` was verified after reboot.
- `PasswordAuthentication yes` and `PubkeyAuthentication yes` remain enabled
  for recovery and the dedicated key login was reverified after reboot.
- The management IPv4 `192.162.1.0/24` is not RFC1918 and remains an explicit
  network-risk follow-up.

## Network, services, and safety checks

- `enp7s0` is up at `192.162.1.21/24`, 100 Mb/s full duplex, with Ethernet as
  the primary default route. Wi-Fi fallback is `192.162.1.6/24` at metric 600.
- UFW is active with default deny incoming and allow outgoing. SSH is scoped to
  `192.162.1.0/24` on IPv4 only; broad IPv4 and IPv6 SSH rules are removed.
- Listening services are SSH on port 22 and loopback system DNS only. No port
  8000 listener or manual FastAPI proof process is running.
- Docker is active with no running workloads; the historical `hello-world`
  container remains exited. PostgreSQL, Home Assistant, MQTT, and product
  containers were not admitted.
- No failed systemd units were reported after reboot. A missing
  `pam_lastlog.so` error remains an observed non-fatal journal warning; no
  critical unit failure was reported.

## Thermal and memory evidence

- Idle cores: Core 0 40 °C, Core 1 39 °C.
- One permitted bounded test: two CPU workers for 30 seconds; Core 0 peak
  62 °C, Core 1 peak 61 °C; 75 °C stop was not reached; stress exited passed.
- Cooldown reading after 30 seconds: Core 0 40 °C, Core 1 38 °C.
- Bounded memory check: 1 GiB for 60 seconds; passed; swap remained at 0 B;
  post-test available memory was approximately 3.5 GiB.
- No second stress test was run.

## Battery and power

- Software exposes only `ACAD online=1`; no `BAT*` device is present.
- Owner visual results: no battery present, no battery swelling/heat possible,
  no case or cover distortion, and no mechanically abnormal fan sound.
- The 30-second AC-removal continuity test was **not run** because a
  battery-less host would necessarily lose power and could not satisfy the
  required running-host/SSH continuity acceptance.

## Storage, logs, backup, and recovery

- Root filesystem is 9% used; `/boot` is 11% used; no LVM resize was performed.
- `smartmontools` was installed from the official Ubuntu repository. SMART
  overall health passed; reallocated, pending, and offline-uncorrectable
  counters were all zero. The historical airflow-temperature marginal
  attribute remains recorded and is not a sector-health failure.
- Journal usage was 79.3 MiB. The applied drop-in bounds system use to 256 MiB,
  runtime use to 128 MiB, and retention to 14 days.
- A configuration-only archive was encrypted with AES-256 GPG, copied to ASUS
  TUF temporary storage, restored on VENOM to a temporary directory, checksum
  verified, and read successfully with 11 files. Temporary VENOM plaintext and
  staging paths were removed; no archive is committed.
- One controlled reboot passed. The boot ID changed from
  `9eb012db-685c-4637-9181-7e0f044cee00` to
  `0722b8e8-1c8c-4268-83f8-eeda51724308`; hostname, key SSH, Ethernet route,
  UFW, timer, failed-unit, and workload recovery were verified.

## Stability monitor

- Preliminary marker `2026-08-18T21:45:13Z` remains historical only; it is
  not counted toward acceptance.
- Official gate start marker: `2026-08-18T22:28:46Z` UTC.
- Official initial boot ID: `0722b8e8-1c8c-4268-83f8-eeda51724308`.
- The scalar-only monitor records UTC time, boot ID, uptime, load, available
  memory, swap use, root use, maximum CPU core temperature, Ethernet state,
  default route, failed units, SMART status, reboot/missing-sample flags, and
  bounded health statuses. It does not collect personal data, history, keys,
  prompts, or command lines.
- The root `venom-phase1-stability.timer` is enabled and active at the approved
  15-minute cadence. The user fallback timer is inactive; historical
  pre-official samples remain preserved. After the official SSH session
  closed, the timer-triggered service completed successfully at
  `2026-08-18T22:28:55Z`, proving collection is not dependent on the user
  session.

## Repository evidence and files

- `infrastructure/home_server/evidence/venom_physical_gate.json`
- `infrastructure/home_server/evidence/venom_stability_summary.json`
- `scripts/phase_01/validate_physical_gate_evidence.py`
- `scripts/phase_01/venom_bounded_thermal_gate.sh`
- `scripts/phase_01/venom_bounded_memory_gate.sh`
- `scripts/phase_01/venom_stability_monitor.sh`
- `scripts/phase_01/venom_privileged_closeout.sh`
- `scripts/phase_01/venom_prepare_config_backup.sh`
- `scripts/phase_01/venom_restore_config_backup.sh`
- `scripts/phase_01/venom_pre_reboot_check.sh`
- `scripts/phase_01/venom_start_official_gate.sh`
- `infrastructure/home_server/systemd/venom-phase1-stability.service`
- `infrastructure/home_server/systemd/venom-phase1-stability.timer`
- documented user-fallback unit and timer
- updated `START_HERE.md`, `docs/IMPLEMENTATION_STATUS.md`,
  `docs/phases/PHASE_01_LENOVO_CONTROL_PLANE_FOUNDATION.md`,
  `infrastructure/home_server/README.md`, and this report

Raw system logs, credentials, private keys, personal data, and temporary
archives were not committed.

## Validation, Git, and CI

Local validation completed on the final pre-commit worktree:

| Command | Result |
|---|---|
| `uv sync --group dev --locked` | Passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run mypy .` | Passed |
| `uv run pytest` | 200 passed, 3 PostgreSQL integration tests skipped because `BMO_TEST_DATABASE_URL` is unset |
| `uv run python scripts/verify_governance.py` | Passed |
| `uv run python scripts/check.py` | Passed; 200 non-integration tests passed and 3 integration tests were skipped |
| `uv run pre-commit run --all-files` | Passed |
| `git diff --check` | Passed |
| `uv run python scripts/phase_01/validate_physical_gate_evidence.py --input infrastructure/home_server/evidence/venom_physical_gate.json` | Passed |

No merge, rebase, amend, force-push, or Phase 5B work was performed. Commit
SHA, push state, PR URL, and exact-head GitHub CI are recorded below after the
normal commit and push.

- Closeout implementation commit: `f43b7310da68faaffb3add32b46958aa9d679824`.
- It was pushed normally to `origin/phase-01/venom-physical-safety-gate`.
- PR #14 remains open, draft, unmerged:
  `https://github.com/MahmoudNagiubX/BMO-Personal-AI-OS/pull/14`.
- Exact-head GitHub CI run `32193450391` (run 82), job `phase-two-checks`,
  passed on that commit.

## Acceptance state

- 24h gate: WAITING.
- 7d gate: WAITING.
- Phase 1 overall: WAITING_FOR_24H; immediate closeout is complete.
- Phase 5B: NOT STARTED.

WAITING_FOR_24H
