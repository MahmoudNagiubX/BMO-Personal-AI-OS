# VENOM Lenovo control-plane foundation

This directory is the repository-side foundation for the verified physical
VENOM host. It does not deploy software, open ports, or replace the canonical
backend under `src/personal_ai_os/`.

## Runtime identity and topology

- Runtime name: `VENOM`
- Hostname: `venom-server`
- Linux user: `venom`
- Host: Lenovo G450, Ubuntu Server 24.04.4 LTS AMD64, headless
- ASUS TUF: Ollama, Qwen3.5 4B generation/vision, and BGE-M3 embeddings
- Repository source of truth: ASUS TUF -> GitHub -> reviewed commit -> Lenovo SSH deployment

The manual `~/venom/core/brain` FastAPI proof-of-life workspace remains
historical bootstrap evidence. It is not production code and must not receive
a second backend implementation. Future deployment comes from an exact,
reviewed repository commit.

## Evidence

`evidence/venom_foundation_handoff.json` is a sanitized owner-provided handoff
record. Validate it with:

```bash
uv run python scripts/phase_01/validate_foundation_evidence.py \
  --input infrastructure/home_server/evidence/venom_foundation_handoff.json
```

The handoff records the completed installation, identity, SMART, and proof of
life facts. It intentionally remains historical. The current authorized
physical-gate session is recorded in
`evidence/venom_physical_gate.json` and
`evidence/venom_stability_summary.json`; immediate privileged closeout and
reboot recovery passed, while these files explicitly preserve the real-time
24-hour and 7-day waiting states and do not claim final acceptance. The NEW
FINAL official marker is `2026-08-19T00:11:05Z`; the preliminary marker and
both earlier official markers remain historical.
The read-only local preflight is available at
`scripts/phase_01/check_foundation_prerequisites.sh`; it must be run by a
human on VENOM when physical access is authorized.

The repeatable bounded runners are
`scripts/phase_01/venom_bounded_thermal_gate.sh`,
`scripts/phase_01/venom_bounded_memory_gate.sh`, and
`scripts/phase_01/venom_stability_monitor.sh`. The privileged deployment uses
the system-level units under `systemd/`. The current closeout verified the
durable root timer and disabled the documented user fallback; the fallback
timer is not durable across logout or reboot while `Linger=no`. The monitor
records SMART sector counters 5, 197, and 198 without serials. Evaluate
sanitized evidence with:

The persistent Core deployment and rollback scripts also enable the existing
`bmo-core` user service before restarting it. This repairs the verified
disabled/inactive-unit failure mode without changing the separate `Linger`
policy or exposing Core beyond `127.0.0.1:8000`.

```bash
uv run python scripts/phase_01/evaluate_stability_gate.py \
  --evidence infrastructure/home_server/evidence/venom_physical_gate.json \
  --marker <official-gate-marker> \
  --samples <sanitized-stability.csv>
```

The effective host lid policy is `ignore` for lid, external power, and docked
operation through `/etc/systemd/logind.conf.d/90-venom-always-on.conf`; remove
that drop-in and restart `systemd-logind` to roll it back.

## Runbooks

- `runbooks/01-foundation-inventory.md` — network, memory, storage, thermal,
  and system evidence.
- `runbooks/02-ssh-firewall.md` — key-auth proof and private-LAN UFW scope.
- `runbooks/03-logs-backup-restore.md` — bounded logs and real restore proof.
- `runbooks/04-reboot-and-stability.md` — restart recovery and 24-hour/7-day gates.

All privileged, physical, destructive, or long-running actions remain manual
owner operations. No runbook authorizes public exposure, blind LVM changes,
uncontrolled stress, final swap sizing, production Docker admission, or Phase
5B deployment.
