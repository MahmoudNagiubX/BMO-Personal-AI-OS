#!/usr/bin/env bash
set -euo pipefail

# Run only after the controlled reboot has returned and immediate recovery
# checks pass.  This starts a new real-time gate; it never backdates a marker.
[[ "${EUID:-1}" -eq 0 ]] || { printf 'ROOT_REQUIRED\n' >&2; exit 1; }

readonly state_dir="/var/lib/venom-phase1"
readonly evidence_dir="$state_dir/evidence"
readonly monitor_path="/usr/local/lib/venom-phase1/venom_stability_monitor.sh"
readonly timer_unit="venom-phase1-stability.timer"
readonly timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
readonly marker_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
readonly boot_id="$(cat /proc/sys/kernel/random/boot_id)"

[[ "$(hostname)" == "venom-server" ]] || { printf 'HOSTNAME_MISMATCH\n' >&2; exit 1; }
[[ -x "$monitor_path" ]] || { printf 'DURABLE_MONITOR_MISSING\n' >&2; exit 1; }
[[ "$(cat /sys/class/net/enp7s0/operstate)" == "up" ]] || {
  printf 'ETHERNET_LINK_NOT_UP\n' >&2
  exit 1
}
ip route show default | grep -Eq '^default .* dev enp7s0([[:space:]]|$)'
sshd -t
sshd_effective="$(sshd -T)"
grep -Fxq 'permitrootlogin no' <<<"$sshd_effective"
grep -Fxq 'pubkeyauthentication yes' <<<"$sshd_effective"
grep -Fxq 'passwordauthentication yes' <<<"$sshd_effective"
ufw_output="$(ufw status verbose)"
grep -Eq '22/tcp[[:space:]]+ALLOW IN[[:space:]]+192\.162\.1\.0/24' <<<"$ufw_output"
! grep -Eq '22/tcp.*Anywhere' <<<"$ufw_output"
[[ -f /etc/systemd/journald.conf.d/90-venom-bounds.conf ]]
grep -Fq 'SystemMaxUse=256M' /etc/systemd/journald.conf.d/90-venom-bounds.conf
grep -Fq 'RuntimeMaxUse=128M' /etc/systemd/journald.conf.d/90-venom-bounds.conf
grep -Fq 'MaxRetentionSec=14day' /etc/systemd/journald.conf.d/90-venom-bounds.conf
systemctl is-active --quiet ssh
systemctl is-active --quiet docker
systemctl is-active --quiet "$timer_unit"
systemctl is-enabled --quiet "$timer_unit"
if systemctl --failed --no-legend --plain | grep -q '[^[:space:]]'; then
  printf 'FAILED_SYSTEM_UNITS_PRESENT\n' >&2
  exit 1
fi
[[ -z "$(docker ps -q)" ]]

mkdir -p "$evidence_dir"
chmod 700 "$state_dir" "$evidence_dir"
if [[ -f "$evidence_dir/stability.csv" ]]; then
  mv "$evidence_dir/stability.csv" "$evidence_dir/stability-pre-official-$marker_stamp.csv"
fi
rm -f "$state_dir/state.env"

marker_tmp="$state_dir/gate-start.env.tmp"
{
  printf 'gate_start_timestamp_utc=%s\n' "$timestamp"
  printf 'initial_boot_id=%s\n' "$boot_id"
  printf 'marker_status=OFFICIAL_REAL_TIME_GATE\n'
} >"$marker_tmp"
chmod 640 "$marker_tmp"
mv -f "$marker_tmp" "$state_dir/gate-start.env"

systemctl start venom-phase1-stability.service
grep -F "${timestamp:0:16}" "$evidence_dir/stability.csv" >/dev/null
grep -F ",$boot_id," "$evidence_dir/stability.csv" >/dev/null

printf 'OFFICIAL_GATE_STARTED timestamp_utc=%s boot_id=%s\n' "$timestamp" "$boot_id"
tail -n 2 "$evidence_dir/stability.csv"
