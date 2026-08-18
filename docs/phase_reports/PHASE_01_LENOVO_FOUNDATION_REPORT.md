# Phase 1 — VENOM physical safety gate report

**Status:** IN PROGRESS — bounded physical evidence is recorded; privileged
follow-ups and real stability windows remain incomplete.

## Scope completed

This report records the authorized physical-gate session from current `main`
at `a02d08a5012938b165e5e26c88708cda9f1bff9e` on
`phase-01/venom-physical-safety-gate`. It preserves the ASUS TUF → GitHub →
reviewed commit → Lenovo SSH workflow, does not reuse the historical Lenovo
branch, and does not begin Phase 5B.

## Completion mode

The session reached a bounded, partial physical qualification but cannot claim
the immediate-work completion mode because the required privileged system timer,
backup/restore proof, reboot recovery, and hardening changes were skipped when
interactive sudo credentials were unavailable. A non-privileged user timer is
active only while the user manager remains available and `Linger=no`.

## Server identity and access

- Runtime: VENOM; hostname: `venom-server`; Linux user: `venom`.
- Hardware: Lenovo G450; Ubuntu Server 24.04.4 LTS AMD64; x86_64; 2 CPU cores;
  approximately 4 GiB RAM.
- Dedicated Ed25519 key login passed from the ASUS TUF.
- Key fingerprint: `SHA256:fAvEE4TUpb4P524E/We6LRsVG9xygEeXT+mL8r/G1Gg`.
- Password login remains enabled as recovery fallback.
- Root SSH was not changed; effective state remains `without-password`.
- The management IPv4 `192.162.1.0/24` is not RFC1918 and remains an explicit
  network-risk follow-up.

## Network, services, and safety checks

- `enp7s0` is up at `192.162.1.21/24`, 100 Mb/s full duplex, with Ethernet as
  the primary default route. Wi-Fi fallback is `192.162.1.6/24` at metric 600.
- UFW is active with default deny incoming and allow outgoing. Existing broad
  SSH rules for IPv4 and IPv6 remain; scoped replacement was not applied.
- Listening services are SSH on port 22 and loopback system DNS only. No port
  8000 listener or manual FastAPI proof process is running.
- Docker is active with no running workloads; the historical `hello-world`
  container remains exited. PostgreSQL, Home Assistant, MQTT, and product
  containers were not admitted.
- No failed systemd units were reported. A missing `pam_lastlog.so` error was
  observed in the journal; no critical unit failure was reported.

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
- Historical SMART handoff is preserved, but current `smartctl` inspection was
  unavailable because `smartctl` is not installed; no package was installed.
- Journal usage was 79.3 MiB with no deliberate local retention bound found.
  The reversible journald drop-in was not applied because privileged sudo work
  was skipped.
- No encrypted off-device configuration backup or temporary restore proof was
  completed. No backup archive was added to the repository.
- No reboot was performed; no reboot/recovery result is claimed.

## Stability monitor

- Gate start marker: `2026-08-18T21:45:13Z`.
- Initial boot ID: `9eb012db-685c-4637-9181-7e0f044cee00`.
- The scalar-only monitor records UTC time, boot ID, uptime, load, available
  memory, swap use, root use, maximum CPU core temperature, Ethernet state,
  default route, failed units, SMART status, reboot/missing-sample flags, and
  bounded health statuses. It does not collect personal data, history, keys,
  prompts, or command lines.
- The required root system timer is not installed. A user-level 15-minute
  fallback timer is active, but `Linger=no`; it is not durable across logout or
  reboot and is not sufficient for final stability acceptance.

## Repository evidence and files

- `infrastructure/home_server/evidence/venom_physical_gate.json`
- `infrastructure/home_server/evidence/venom_stability_summary.json`
- `scripts/phase_01/validate_physical_gate_evidence.py`
- `scripts/phase_01/venom_bounded_thermal_gate.sh`
- `scripts/phase_01/venom_bounded_memory_gate.sh`
- `scripts/phase_01/venom_stability_monitor.sh`
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
| `uv run pytest` | 196 passed, 3 PostgreSQL integration tests skipped because `BMO_TEST_DATABASE_URL` is unset |
| `uv run python scripts/verify_governance.py` | Passed |
| `uv run python scripts/check.py` | Passed; 196 non-integration tests passed and 3 integration tests were skipped |
| `uv run pre-commit run --all-files` | Passed |
| `git diff --check` | Passed |
| `uv run python scripts/phase_01/validate_physical_gate_evidence.py --input infrastructure/home_server/evidence/venom_physical_gate.json` | Passed |

No merge, rebase, amend, force-push, or Phase 5B work is allowed. Commit SHA,
push state, PR URL, and exact-head GitHub CI are recorded below after the
normal commit and push.

## Acceptance state

- 24h gate: WAITING.
- 7d gate: WAITING.
- Phase 1 overall: IN PROGRESS.
- Phase 5B: NOT STARTED.

BLOCKED — required privileged hardening, encrypted backup/restore, durable
system monitoring, and reboot recovery were not performed without interactive
sudo authorization; real 24-hour and 7-day evidence is also pending.
