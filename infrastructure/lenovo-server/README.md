# Lenovo G450 Control Plane Infrastructure Baseline

This directory contains the automated bootstrap script and usage documentation for establishing the always-on BMO Control Plane baseline on the Lenovo G450.

## Target Hardware & OS Specs

- **Hardware:** Lenovo G450 (Core 2 Duo, 4 GB RAM, internal HDD/SSD)
- **Role:** Always-on BMO Control Plane & Home Edge Hub (ADR-0003)
- **Target OS:** Ubuntu Server 24.04 LTS (64-bit, headless, no desktop environment)
- **Architecture:** `x86_64`

## Prerequisites & Manual Safety Gate

Before installing Ubuntu Server or running `bootstrap.sh`:

1. **Hardware Inspection:** Confirm battery is not swollen, charger is intact, cooling fan functions, and physical Ethernet port is operational.
2. **Data Backup:** Ensure all required personal files on the Lenovo internal disk are backed up.
3. **Disk Erase Approval:** Confirm authorization for complete disk erasure.
4. **Bootable USB Creation:**
   - Download official Ubuntu Server 24.04 LTS 64-bit ISO from `https://releases.ubuntu.com/24.04/`.
   - Verify published SHA-256 checksum.
   - Flash to an 8 GB+ USB drive using Rufus or Balena Etcher (select MBR/BIOS or UEFI depending on firmware support).
5. **Ubuntu Installation:**
   - Hostname: `bmo-control`
   - User: create non-root admin account
   - OpenSSH: enable during install
   - Snaps: none selected
6. **SSH Key Setup:**
   - Copy public key from the ASUS TUF (`ssh-copy-id`) beforeHardening.
   - Verify key authentication succeeds before disabling password login.

## Automated Baseline Setup

Once booted into Ubuntu Server 24.04 LTS:

```bash
git clone https://github.com/MahmoudNagiubX/BMO-Personal-AI-OS.git
cd BMO-Personal-AI-OS
sudo ./infrastructure/lenovo-server/bootstrap.sh
```

`bootstrap.sh` performs:
- Package updates and installation of diagnostic utilities (`smartmontools`, `lm-sensors`, `curl`, `jq`, `ufw`, `git`).
- Timezone configuration to `Africa/Cairo`.
- SSH hardening drop-in (`/etc/ssh/sshd_config.d/99-bmo-hardening.conf`).
- UFW firewall setup (default deny incoming, allow OpenSSH).
- Official Docker Engine and Docker Compose plugin installation via official Docker apt repository.
- Docker daemon log rotation (`max-size: 10m`, `max-file: 3`).

## Verification Commands

Run after `bootstrap.sh`:

```bash
hostnamectl
timedatectl
free -h
swapon --show
df -h
sudo ufw status verbose
sudo systemctl is-active ssh
sudo systemctl is-active docker
docker --version
docker compose version
sensors
sudo smartctl -H /dev/sda
sudo systemctl --failed
```

## Recovery & Rollback

- **Network Lockout Recovery:** Log in directly via physical keyboard and monitor on the Lenovo.
- **Service Reset:** `sudo systemctl restart docker ssh ufw`
- **Reinstall:** Re-boot from the Ubuntu Server USB installer to re-flash the OS if baseline corrupted.
