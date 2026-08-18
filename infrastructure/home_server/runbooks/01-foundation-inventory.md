# Runbook 01 — VENOM foundation inventory

Human execution on the physical Lenovo is required. Do not SSH from an agent
or run this during the repository task. The commands below are read-only and
bounded; save only reviewed scalar results as sanitized evidence.

1. Run `scripts/phase_01/check_foundation_prerequisites.sh` locally on VENOM.
2. Confirm the normal path with:

   ```bash
   ip -br addr
   ip route
   networkctl status enp7s0 || true
   ethtool enp7s0
   ```

   Record Ethernet link state, default route, speed, and duplex. Do not set a
   static address before topology inspection; use a DHCP reservation only
   after review.

3. Record bounded memory evidence:

   ```bash
   free -h
   swapon --show
   cat /proc/meminfo | head -n 20
   sudo dmidecode --type memory
   ```

   Do not allocate all RAM or select a final swap size in this runbook.

4. Record storage and LVM evidence:

   ```bash
   lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL
   df -hT
   sudo pvs
   sudo vgs
   sudo lvs
   ```

   Do not resize LVM automatically.

5. Record idle thermal evidence before any bounded CPU test:

   ```bash
   sensors
   cat /proc/loadavg
   uptime
   ```

   Never run uncontrolled stress or a full-memory test. Accept thermals only
   with measured bounded-load temperature, fan behavior, and no shutdown or
   freeze.

6. Record battery presence, physical condition, charging, AC-removal, and
   recovery behavior. Never deep-discharge an old battery. A swollen, very hot,
   or damaged battery is a hard safety blocker.

7. Record the system baseline:

   ```bash
   cat /etc/os-release
   uname -a
   hostnamectl
   timedatectl
   systemctl --failed
   sudo journalctl -p 3 -b --no-pager
   ```

The repository handoff is not updated until the owner reviews the captured
results and explicitly records the next gate status.
