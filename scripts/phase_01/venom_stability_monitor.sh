#!/usr/bin/env bash
set -euo pipefail

# Scalar-only, bounded Phase 1 monitor. It never reads user homes, command
# lines, prompts, browser data, private keys, or model output.

readonly state_dir="${VENOM_PHASE1_STATE_DIR:-/var/lib/venom-phase1}"
readonly evidence_dir="$state_dir/evidence"
readonly marker_path="$state_dir/gate-start.env"
readonly state_path="$state_dir/state.env"
readonly samples_path="$evidence_dir/stability.csv"
readonly max_data_rows=1000

mkdir -p "$evidence_dir"

read_state() {
  local key="$1"
  if [[ -r "$state_path" ]]; then
    awk -F= -v wanted="$key" '$1 == wanted { print substr($0, index($0, "=") + 1); exit }' "$state_path"
  fi
}

read_marker() {
  local key="$1"
  if [[ -r "$marker_path" ]]; then
    awk -F= -v wanted="$key" '$1 == wanted { print substr($0, index($0, "=") + 1); exit }' "$marker_path"
  fi
}

now_epoch="$(date +%s)"
timestamp_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
boot_id="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf 'unavailable')"
uptime_seconds="$(awk '{printf "%d", $1}' /proc/uptime)"
read -r load_1 load_5 load_15 _ < /proc/loadavg
mem_available_bytes="$(awk '/^MemAvailable:/ { print $2 * 1024; exit }' /proc/meminfo)"
swap_used_bytes="$(free -b | awk '/^Swap:/ { print $3; exit }')"
root_used_percent="$(df -P / | awk 'NR == 2 { gsub(/%/, "", $5); print $5; exit }')"
max_core_temp_c="$(sensors 2>/dev/null | awk '/Core [01]:/ { value = $3; gsub(/[^0-9.]/, "", value); if (value > maximum) maximum = value } END { if (maximum == "") print "NA"; else print maximum }')"
ethernet_link="$(cat /sys/class/net/enp7s0/operstate 2>/dev/null || printf 'unavailable')"
default_route_interface="$(ip route show default 2>/dev/null | awk '$1 == "default" { print $5; exit }')"
default_route_interface="${default_route_interface:-unavailable}"
failed_units="$(systemctl --failed --no-legend --plain 2>/dev/null | awk 'NF { count++ } END { print count + 0 }')"
ssh_active="$(systemctl is-active ssh 2>/dev/null || printf 'unknown')"
ufw_output="$(ufw status 2>/dev/null || true)"
ufw_active="unknown"
if [[ "$ufw_output" == "Status: active"* ]]; then
  ufw_active="active"
fi

previous_epoch="$(read_state last_epoch)"
previous_boot_id="$(read_state last_boot_id)"
sample_number="$(read_state sample_number)"
last_smart_status="$(read_state last_smart_status)"
previous_epoch="${previous_epoch:-0}"
sample_number="${sample_number:-0}"
last_smart_status="${last_smart_status:-unavailable}"
sample_gap_seconds=0
if [[ "$previous_epoch" =~ ^[0-9]+$ ]] && (( previous_epoch > 0 )); then
  sample_gap_seconds=$((now_epoch - previous_epoch))
fi
((sample_number += 1))

reboot_detected=0
if [[ -n "$previous_boot_id" && "$previous_boot_id" != "$boot_id" ]]; then
  reboot_detected=1
fi
if [[ -r "$marker_path" ]]; then
  marker_boot_id="$(read_marker initial_boot_id)"
  if [[ -n "$marker_boot_id" && "$marker_boot_id" != "$boot_id" ]]; then
    reboot_detected=1
  fi
else
  marker_boot_id="missing"
fi

if (( sample_number % 4 == 1 )) && command -v smartctl >/dev/null 2>&1; then
  smart_health_output="$(smartctl -H /dev/sda 2>/dev/null || true)"
  if grep -q 'SMART overall-health self-assessment test result: PASSED' <<<"$smart_health_output"; then
    last_smart_status="passed"
  else
    last_smart_status="not_passed_or_unavailable"
  fi
fi

thermal_status="pass"
if [[ "$max_core_temp_c" != "NA" ]] && awk -v value="$max_core_temp_c" 'BEGIN { exit !(value >= 75) }'; then
  thermal_status="breach"
fi
disk_status="pass"
if [[ "$root_used_percent" =~ ^[0-9]+$ ]] && (( root_used_percent >= 90 )); then
  disk_status="breach"
fi
swap_status="clear"
if [[ "$swap_used_bytes" =~ ^[0-9]+$ ]] && (( swap_used_bytes > 0 )); then
  swap_status="used"
fi
network_status="degraded"
if [[ "$ethernet_link" == "up" && "$default_route_interface" == "enp7s0" ]]; then
  network_status="up"
fi
missing_sample=0
if (( sample_gap_seconds > 1800 )); then
  missing_sample=1
fi

if [[ ! -f "$samples_path" ]]; then
  printf '%s\n' 'timestamp_utc,boot_id,uptime_seconds,load_1,load_5,load_15,mem_available_bytes,swap_used_bytes,root_used_percent,max_core_temp_c,ethernet_link,default_route_interface,failed_units,smart_status,ssh_active,ufw_active,reboot_detected,sample_gap_seconds,missing_sample,thermal_status,disk_status,swap_status,network_status' >"$samples_path"
fi
printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "$timestamp_utc" "$boot_id" "$uptime_seconds" "$load_1" "$load_5" "$load_15" \
  "$mem_available_bytes" "$swap_used_bytes" "$root_used_percent" "$max_core_temp_c" \
  "$ethernet_link" "$default_route_interface" "$failed_units" "$last_smart_status" \
  "$ssh_active" "$ufw_active" "$reboot_detected" "$sample_gap_seconds" "$missing_sample" \
  "$thermal_status" "$disk_status" "$swap_status" "$network_status" >>"$samples_path"

if [[ "$(wc -l <"$samples_path")" -gt $((max_data_rows + 1)) ]]; then
  tmp_path="${samples_path}.tmp"
  { head -n 1 "$samples_path"; tail -n "$max_data_rows" "$samples_path"; } >"$tmp_path"
  mv -f "$tmp_path" "$samples_path"
fi

state_tmp="${state_path}.tmp"
{
  printf 'last_epoch=%s\n' "$now_epoch"
  printf 'last_boot_id=%s\n' "$boot_id"
  printf 'sample_number=%s\n' "$sample_number"
  printf 'last_smart_status=%s\n' "$last_smart_status"
} >"$state_tmp"
mv -f "$state_tmp" "$state_path"
