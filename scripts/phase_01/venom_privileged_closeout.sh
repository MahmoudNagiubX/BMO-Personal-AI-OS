#!/usr/bin/env bash
set -euo pipefail

# Secret-free privileged Phase 1 closeout. This script deliberately stops
# before encrypted backup, reboot, and the official stability-clock reset.
# Those steps require separate interactive owner checkpoints.

readonly monitor_script=/tmp/venom_stability_monitor.sh
readonly monitor_service=/tmp/venom-phase1-stability.service
readonly monitor_timer=/tmp/venom-phase1-stability.timer
readonly state_dir=/var/lib/venom-phase1

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run this script through sudo.\n' >&2
  exit 1
fi

for required in "$monitor_script" "$monitor_service" "$monitor_timer"; do
  [[ -r "$required" ]] || { printf 'Missing reviewed input: %s\n' "$required" >&2; exit 1; }
done

if ! command -v smartctl >/dev/null 2>&1; then
  apt-get update
  apt-get install -y smartmontools
fi

install -d -m 0755 "$state_dir"
smart_health_path="$state_dir/smartctl-health.txt"
smart_health_status=0
smartctl -H /dev/sda >"$smart_health_path" 2>&1 || smart_health_status=$?
cat "$smart_health_path"
if ! grep -Fq 'SMART overall-health self-assessment test result: PASSED' "$smart_health_path"; then
  printf 'SMART overall health did not pass. Stop before host hardening.\n' >&2
  exit 1
fi
smart_attributes_path="$state_dir/smartctl-attributes.txt"
smart_attribute_status=0
smartctl -A /dev/sda >"$smart_attributes_path" 2>&1 || smart_attribute_status=$?
cat "$smart_attributes_path"
if ! awk '$1 == 5 || $1 == 197 || $1 == 198 { if ($10 != 0) bad = 1 } END { exit bad }' "$smart_attributes_path"; then
  printf 'SMART safety counters are not all zero. Stop before host hardening.\n' >&2
  exit 1
fi

install -d -m 0755 /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/90-venom-phase1.conf <<'EOF'
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication yes
EOF
chmod 0644 /etc/ssh/sshd_config.d/90-venom-phase1.conf
sshd -t
systemctl reload ssh

if ! ufw status | grep -Fq '192.162.1.0/24'; then
  ufw allow from 192.162.1.0/24 to any port 22 proto tcp
fi
ufw status numbered
ufw status verbose

install -d -m 0755 /etc/systemd/journald.conf.d
journalctl --disk-usage >"$state_dir/journal-before.txt"
systemd-analyze cat-config systemd/journald.conf >"$state_dir/journal-effective-before.txt"
cat >/etc/systemd/journald.conf.d/90-venom-bounds.conf <<'EOF'
[Journal]
SystemMaxUse=256M
RuntimeMaxUse=128M
MaxRetentionSec=14day
EOF
chmod 0644 /etc/systemd/journald.conf.d/90-venom-bounds.conf
systemctl restart systemd-journald
logger 'VENOM Phase 1 journald verification'
journalctl --disk-usage
journalctl -n 20 --no-pager

install -d -m 0755 /usr/local/lib/venom-phase1 "$state_dir/evidence"
install -m 0755 "$monitor_script" /usr/local/lib/venom-phase1/venom_stability_monitor.sh
install -m 0644 "$monitor_service" /etc/systemd/system/venom-phase1-stability.service
install -m 0644 "$monitor_timer" /etc/systemd/system/venom-phase1-stability.timer
if [[ ! -f "$state_dir/gate-start.env" ]]; then
  {
    printf 'gate_start_timestamp=%s\n' 'PRELIMINARY_NOT_OFFICIAL'
    printf 'initial_boot_id=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
  } >"$state_dir/gate-start.env"
  chmod 0644 "$state_dir/gate-start.env"
fi

systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/venom-phase1-stability.service /etc/systemd/system/venom-phase1-stability.timer
systemctl enable --now venom-phase1-stability.timer
systemctl start venom-phase1-stability.service
systemctl is-enabled venom-phase1-stability.timer
systemctl is-active venom-phase1-stability.timer
systemctl status venom-phase1-stability.service --no-pager

printf 'Privileged pre-backup closeout complete; official stability clock remains unopened.\n'
