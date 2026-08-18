# Runbook 04 — reboot recovery and stability gates

The owner must schedule these checks around real availability needs. Codex does
not reboot or stress the physical host as part of repository work.

1. Before reboot, record hostname, uptime, failed units, free memory/swap,
   root free space, temperature, and listening services.
2. Reboot only after the recovery path is confirmed. Verify network, SSH,
   hostname `venom-server`, active UFW, and only intended auto-start services.
3. Monitor the host through a bounded evidence cadence. Record unexpected
   reboots, kernel/storage errors, thermal readings, memory/swap pressure,
   free-space trend, and network/SSH availability.
4. Pass a continuous 24-hour gate, then a continuous 7-day gate. Do not claim
   `PHASE 1 / LENOVO SAFETY GATE — PASS` until both gates and backup/restore,
   power, firewall, and resource checks pass.

The repository-side Phase 1 report remains `IN PROGRESS` until the owner
provides and reviews these physical results.
