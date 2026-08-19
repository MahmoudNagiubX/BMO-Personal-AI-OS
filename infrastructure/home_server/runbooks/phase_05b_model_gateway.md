# Phase 5B model-gateway deployment

This runbook deploys only the accepted Phase 5A gateway package and a scalar health probe to
VENOM. Ollama and both active models remain on the ASUS TUF. The transport is a reverse SSH
forward from TUF loopback to VENOM loopback; port 11434 is never exposed to the LAN.

## Reviewed deployment

1. On the TUF, create the dedicated key with `new_tunnel_key.ps1`. Its private half stays under
   the current Windows user's `.ssh` directory and is never copied or printed.
2. Copy only the `.pub` file and `scripts/phase_05b/install_venom.sh` to `/tmp` on VENOM.
3. Review and interactively run the installer with the exact tested 40-character commit and the
   canonical GitHub repository URL. The installer creates the non-sudo, key-only `bmo-tunnel`
   identity and validates a `Match User` policy with `AllowTcpForwarding remote`, `PermitOpen
   none`, and `PermitListen 127.0.0.1:11434` before reloading SSH. It checks out that exact commit,
   installs only the gateway's two pinned configuration dependencies, and enables the scalar probe
   timer.
4. Start and verify the tunnel with `manage_tunnel.ps1`, then use `install_tunnel_task.ps1` to
   register the limited current-user Scheduled Task. The reviewed installer gives Task Scheduler
   direct ownership of the fixed OpenSSH action so stopping the task also stops the tunnel process.

The normal `venom` administrator SSH key remains separate and outside the `Match User` policy.
The tunnel identity has no sudo/product groups and no usable password authentication. No password
is stored by these scripts.

## Verification

- TUF: port 11434 has only loopback listeners and Ollama reports version 0.32.5.
- VENOM: port 11434 has only a loopback reverse-forward listener; UFW has no Ollama rule.
- `/var/lib/bmo-phase5b/gateway-health.json` contains only typed/scalar health fields.
- An offline TUF produces an `offline` observation while the oneshot systemd service exits 0.
- `test_tunnel_policy.ps1` proves local forwarding, dynamic forwarding, and an alternate remote
  listener are denied. Stop the canonical tunnel before this bounded test, then restore it and
  verify exact model availability afterward.
- Interactively run the reviewed `verify_venom_security_closeout.sh` with sudo only after staging
  and hash verification. It reads the effective SSH/UFW/listener/monitor state and changes no
  service or configuration.

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

Then remove `/etc/ssh/sshd_config.d/91-bmo-phase5b-tunnel.conf` and the `bmo-tunnel` identity only
after `sshd -t` passes for the rollback configuration. Reload SSH; do not change the normal
`venom` administrator authorization. The exact installer backup under
`/var/lib/bmo-phase5b/security-recovery-backup-<commit>` supports bounded restoration. The release
and scalar state may be retained for forensics. Rollback leaves Phase 1 monitoring, SSH hardening,
UFW, historical evidence, models, and the bootstrap proof untouched.
