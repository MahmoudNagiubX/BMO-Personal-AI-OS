#!/usr/bin/env bash
set -euo pipefail

# One-shot, bounded Phase 1 thermal closeout. This is intentionally a small
# operator-facing script: it does not change governors, fan policy, or limits.

readonly duration_seconds="${1:-30}"
readonly evidence_dir="${2:-$HOME/venom-gate-evidence/thermal}"
readonly csv_path="$evidence_dir/thermal-${duration_seconds}s.csv"
readonly summary_path="$evidence_dir/thermal-${duration_seconds}s.txt"
readonly stress_path="$evidence_dir/stress-ng-${duration_seconds}s.txt"
readonly threshold_c=75

mkdir -p "$evidence_dir"

read_core_temp() {
  local core_label="$1"
  sensors 2>/dev/null | awk -v label="$core_label" '
    $0 ~ label ":" {
      value = $3
      gsub(/[^0-9.]/, "", value)
      print value
      exit
    }
  '
}

max_value() {
  awk -v left="${1:-}" -v right="${2:-}" 'BEGIN {
    if (left == "") left = -1
    if (right == "") right = -1
    print (left > right ? left : right)
  }'
}

sample() {
  local phase="$1"
  local timestamp core0 core1
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  core0="$(read_core_temp 'Core 0')"
  core1="$(read_core_temp 'Core 1')"
  printf '%s,%s,%s,%s\n' "$timestamp" "$phase" "$core0" "$core1" >>"$csv_path"
  if [[ "$phase" == "idle" ]]; then
    idle_core0="$core0"
    idle_core1="$core1"
  elif [[ "$phase" == "stress" ]]; then
    peak_core0="$(max_value "$peak_core0" "$core0")"
    peak_core1="$(max_value "$peak_core1" "$core1")"
  else
    post_core0="$core0"
    post_core1="$core1"
  fi
  if [[ "$phase" == "stress" ]] && awk -v a="${core0:-0}" -v b="${core1:-0}" -v limit="$threshold_c" 'BEGIN { exit !((a >= limit) || (b >= limit)) }'; then
    thermal_stop=1
  fi
}

: >"$csv_path"
printf 'timestamp_utc,phase,core0_c,core1_c\n' >>"$csv_path"
idle_core0=""
idle_core1=""
peak_core0=""
peak_core1=""
post_core0=""
post_core1=""
thermal_stop=0
stress_status="not_started"

sample idle

stress-ng --cpu 2 --timeout "${duration_seconds}s" --metrics-brief >"$stress_path" 2>&1 &
stress_pid=$!
started_at="$(date +%s)"
while kill -0 "$stress_pid" 2>/dev/null; do
  sample stress
  if [[ "$thermal_stop" -eq 1 ]]; then
    kill -TERM "$stress_pid" 2>/dev/null || true
    stress_status="stopped_at_${threshold_c}C"
    break
  fi
  if (( $(date +%s) - started_at >= duration_seconds )); then
    break
  fi
  sleep 1
done

if wait "$stress_pid"; then
  [[ "$stress_status" == "not_started" ]] && stress_status="passed"
else
  [[ "$stress_status" == "not_started" ]] && stress_status="failed"
fi

sample post

cat >"$summary_path" <<EOF
thermal_gate=bounded
duration_seconds=$duration_seconds
threshold_c=$threshold_c
idle_core0_c=${idle_core0:-unavailable}
idle_core1_c=${idle_core1:-unavailable}
peak_core0_c=${peak_core0:-unavailable}
peak_core1_c=${peak_core1:-unavailable}
post_core0_c=${post_core0:-unavailable}
post_core1_c=${post_core1:-unavailable}
stress_status=$stress_status
thermal_stop=$thermal_stop
csv=$csv_path
stress_log=$stress_path
EOF

cat "$summary_path"
if [[ "$thermal_stop" -eq 1 || "$stress_status" != "passed" ]]; then
  exit 2
fi
