# Phase 5B model-gateway deployment

This runbook deploys only the accepted Phase 5A gateway package and a scalar health probe to
VENOM. Ollama and both active models remain on the ASUS TUF. The transport is a reverse SSH
forward from TUF loopback to VENOM loopback; port 11434 is never exposed to the LAN.

## Reviewed deployment

1. On the TUF, create the dedicated key with `new_tunnel_key.ps1`. Its private half stays under
   the current Windows user's `.ssh` directory and is never copied or printed.
2. Copy only the `.pub` file and `scripts/phase_05b/install_venom.sh` to `/tmp` on VENOM.
3. Review and interactively run the installer with the exact tested 40-character commit and the
   canonical GitHub repository URL. The installer restricts the dedicated key to reverse
   forwarding on `127.0.0.1:11434`, checks out that exact commit, installs only the gateway's two
   pinned configuration dependencies, and enables the scalar probe timer.
4. Start and verify the tunnel with `manage_tunnel.ps1`, then use `install_tunnel_task.ps1` to
   register the limited current-user Scheduled Task. The reviewed installer gives Task Scheduler
   direct ownership of the fixed OpenSSH action so stopping the task also stops the tunnel process.

The normal administrator SSH key remains separate and is used only for read-only verification.
No password is stored by these scripts.

## Verification

- TUF: port 11434 has only loopback listeners and Ollama reports version 0.32.5.
- VENOM: port 11434 has only a loopback reverse-forward listener; UFW has no Ollama rule.
- `/var/lib/bmo-phase5b/gateway-health.json` contains only typed/scalar health fields.
- An offline TUF produces an `offline` observation while the oneshot systemd service exits 0.

## Rollback

On TUF, remove the Scheduled Task with `install_tunnel_task.ps1 -Action Remove`, then stop the
reviewed tunnel with `manage_tunnel.ps1 -Action Stop`. This does not stop or delete Ollama or its
models and does not affect the normal administrator SSH key.

On VENOM, an owner may interactively run:

```sh
sudo systemctl disable --now bmo-phase5b-gateway-probe.timer
sudo rm -f /etc/systemd/system/bmo-phase5b-gateway-probe.service \
  /etc/systemd/system/bmo-phase5b-gateway-probe.timer
sudo systemctl daemon-reload
```

Then remove only the `bmo-phase05b-tunnel` line from `/home/venom/.ssh/authorized_keys`. The
release under `/opt/bmo-phase5b` and scalar state under `/var/lib/bmo-phase5b` may be retained for
forensics or removed after owner review. Rollback leaves Phase 1 monitoring, SSH hardening, UFW,
historical evidence, and the bootstrap `~/venom/core/brain` proof untouched. No database rollback
or model deletion is needed.
