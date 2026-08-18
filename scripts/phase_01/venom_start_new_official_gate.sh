#!/usr/bin/env bash
set -euo pipefail

# Deploy the reviewed monitor schema, make VENOM safe for unattended parked
# operation, and start a new real-time gate. All timestamps are generated on
# VENOM; this script never accepts a caller-supplied clock or secret.
[[ "${EUID:-1}" -eq 0 ]] || { printf 'ROOT_REQUIRED\n' >&2; exit 1; }

readonly monitor_source=/tmp/venom_stability_monitor.sh
readonly service_source=/tmp/venom-phase1-stability.service
readonly timer_source=/tmp/venom-phase1-stability.timer
readonly install_dir=/usr/local/lib/venom-phase1
readonly state_dir=/var/lib/venom-phase1
readonly evidence_dir="$state_dir/evidence"
readonly logind_dropin=/etc/systemd/logind.conf.d/90-venom-always-on.conf
readonly timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
readonly archive_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
readonly boot_id="$(cat /proc/sys/kernel/random/boot_id)"

for required in "$monitor_source" "$service_source" "$timer_source"; do
  [[ -r "$required" ]] || { printf 'MISSING_REVIEWED_INPUT=%s\n' "$required" >&2; exit 1; }
done
bash -n "$monitor_source"

install -d -m 0755 "$install_dir" "$evidence_dir" /etc/systemd/logind.conf.d
install -m 0755 "$monitor_source" "$install_dir/venom_stability_monitor.sh"
install -m 0644 "$service_source" /etc/systemd/system/venom-phase1-stability.service
install -m 0644 "$timer_source" /etc/systemd/system/venom-phase1-stability.timer

cat >"$logind_dropin" <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
EOF
chmod 0644 "$logind_dropin"

systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/venom-phase1-stability.service /etc/systemd/system/venom-phase1-stability.timer
systemctl enable --now venom-phase1-stability.timer
systemctl restart systemd-logind

grep -Fq 'HandleLidSwitch=ignore' "$logind_dropin"
grep -Fq 'HandleLidSwitchExternalPower=ignore' "$logind_dropin"
grep -Fq 'HandleLidSwitchDocked=ignore' "$logind_dropin"
systemctl is-active --quiet venom-phase1-stability.timer
systemctl is-enabled --quiet venom-phase1-stability.timer

mkdir -p "$evidence_dir"
chmod 700 "$state_dir" "$evidence_dir"
if [[ -f "$state_dir/gate-start.env" ]]; then
  mv "$state_dir/gate-start.env" "$state_dir/gate-start-pre-new-official-$archive_stamp.env"
fi
if [[ -f "$evidence_dir/stability.csv" ]]; then
  mv "$evidence_dir/stability.csv" "$evidence_dir/stability-pre-new-official-$archive_stamp.csv"
fi
if [[ -f "$state_dir/state.env" ]]; then
  mv "$state_dir/state.env" "$state_dir/state-pre-new-official-$archive_stamp.env"
fi

marker_tmp="$state_dir/gate-start.env.tmp"
{
  printf 'gate_start_timestamp_utc=%s\n' "$timestamp"
  printf 'initial_boot_id=%s\n' "$boot_id"
  printf 'marker_status=OFFICIAL_REAL_TIME_GATE\n'
} >"$marker_tmp"
chmod 0640 "$marker_tmp"
mv -f "$marker_tmp" "$state_dir/gate-start.env"

systemctl start venom-phase1-stability.service
head -n 1 "$evidence_dir/stability.csv" | grep -Fq 'smart_reallocated_sectors'
grep -F ",$boot_id," "$evidence_dir/stability.csv" >/dev/null
printf 'NEW_OFFICIAL_GATE_STARTED timestamp_utc=%s boot_id=%s\n' "$timestamp" "$boot_id"
printf 'LID_POLICY=ignore\n'
printf 'ROOT_TIMER=active_enabled\n'
tail -n 2 "$evidence_dir/stability.csv"
