# Runbook 04 — reboot recovery and stability gates

The owner must schedule these checks around real availability needs. A reboot
is permitted only in an explicitly owner-authorized physical-gate task after
the backup/restore and immediate recovery prerequisites pass. Uncontrolled
stress is never implied by this runbook.

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

## Current VENOM closeout state

One authorized controlled reboot recovered successfully. The official scalar
monitor is enabled through the root system timer, and the real-time gate began
at `2026-08-18T22:28:46Z` UTC. The 24-hour and seven-day gates are WAITING;
Phase 5B remains blocked.

The repository-side Phase 1 report remains `WAITING_FOR_24H` until the owner
reviews the elapsed real-time evidence and both stability gates pass.
