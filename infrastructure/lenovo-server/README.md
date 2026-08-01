# Lenovo Control Plane Preparation

## Purpose

Prepare the Lenovo control-plane baseline for a later, owner-controlled Ubuntu Server installation. The target configuration follows ADR-0003; this directory is not evidence that the target exists on the Lenovo.

## Current state

- The bootstrap script is prepared but has not been executed on the Lenovo.
- No Ubuntu installation, SSH configuration, firewall activation, Docker installation, reboot, SMART check, temperature check, or systemd health check is verified here.
- The physical hardware safety gate and disk-erasure decision are pending.

## Preconditions

Before installation, the owner must inspect the Lenovo, preserve any needed files, authorize disk erasure, verify the charger/battery/fan, and confirm direct physical access, Ethernet, installation media, and sustained power. The planned target is Ubuntu Server 24.04 LTS on a supported 64-bit Lenovo system, with target hostname `bmo-control` and timezone `Africa/Cairo`.

Create and verify the owner's SSH public key during installation. Complete key-login verification in a second session before any later owner-controlled password-authentication change and before SSH hardening.

## Preflight usage

Run on the physically verified Lenovo after Ubuntu is installed:

```bash
sudo ./infrastructure/lenovo-server/bootstrap.sh --preflight
```

`--preflight` is read-only. It reports Ubuntu and architecture, systemd, privilege requirements, official Ubuntu/Docker DNS and HTTPS reachability, disk space, SSH/UFW/Docker state, swap, and expected tools. It does not install packages or change configuration.

## Apply usage and confirmation

After preflight and the owner gate pass:

```bash
sudo env BMO_LENOVO_BOOTSTRAP_CONFIRM=YES \
  ./infrastructure/lenovo-server/bootstrap.sh --apply
```

`--apply` requires the exact confirmation value, root, Ubuntu on x86_64/amd64, systemd as PID 1, non-WSL Linux, network/DNS reachability, and sufficient disk space. The script never infers Lenovo identity from a hostname.

## What the script changes

- Installs the planned administration, diagnostic, OpenSSH, UFW, and Docker packages.
- Sets the target timezone.
- Installs and validates a managed SSH drop-in with `PermitRootLogin no` and `PubkeyAuthentication yes`.
- Allows only the OpenSSH UFW application before non-interactive enablement; existing unrelated rules are not silently removed.
- Adds the official Docker signing key as a file and a signed apt source, then installs Docker Engine and the Compose plugin.
- Validates `/etc/docker/daemon.json`, preserves compatible existing JSON settings, and enforces bounded JSON log rotation (`10m`, `3`).
- Creates timestamped backups outside the repository when an existing managed SSH drop-in, Docker apt source, or Docker daemon configuration actually changes.
- Enables Docker on boot, checks `docker info`, runs the temporary `hello-world` check, and removes its image when practical.

## What the script intentionally does not change

It does not install Ubuntu, identify hardware, erase or partition disks, create secrets or keys, reboot or shut down, change firmware/router settings, create public Docker TCP access, resize or create swap, or disable password authentication. It never executes a remote installer pipeline. SSH syntax failure restores the managed drop-in and stops before service restart.

## Mandatory manual post-run checks

The owner must collect and review evidence for:

```bash
hostnamectl
timedatectl
free -h
swapon --show
df -h
sudo ufw status verbose
sudo systemctl is-active ssh
docker --version
docker compose version
sudo systemctl is-active docker
sensors
sudo smartctl -H <verified-disk-device>
sudo systemctl --failed
```

Then perform a clean reboot and repeat the service, temperature, storage, and systemd checks. Record the actual Ubuntu version, firmware mode, disk result, RAM stability, Ethernet reliability, charger/battery/fan condition, and recovery behavior before calling the Lenovo health gate complete.

## Recovery notes

If SSH validation fails, the script does not restart SSH; use the local keyboard/display and inspect the timestamped backup beside the managed drop-in. If a firewall or service problem prevents remote access, use direct physical access and review `ufw status verbose`, `systemctl status ssh`, and `systemctl status docker`. Do not delete backups until the owner has verified recovery.
