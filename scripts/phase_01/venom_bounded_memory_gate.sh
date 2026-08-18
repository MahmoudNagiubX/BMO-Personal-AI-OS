#!/usr/bin/env bash
set -euo pipefail

# Bounded memory qualification. It deliberately stays below the 4 GiB host
# capacity and does not alter swap configuration or system memory policy.

readonly duration_seconds="${1:-60}"
readonly evidence_dir="${2:-$HOME/venom-gate-evidence/memory}"
readonly output_path="$evidence_dir/memory-${duration_seconds}s.txt"
readonly allocation_bytes=$((1024 * 1024 * 1024))

mkdir -p "$evidence_dir"
{
  echo "memory_gate=bounded"
  echo "duration_seconds=$duration_seconds"
  echo "allocation_bytes=$allocation_bytes"
  echo "before="
  free -b
  echo "swap_before="
  swapon --show
} >"$output_path"

stress-ng --vm 1 --vm-bytes 1G --vm-keep --timeout "${duration_seconds}s" --metrics-brief >>"$output_path" 2>&1 &
stress_pid=$!
while kill -0 "$stress_pid" 2>/dev/null; do
  printf 'sample_utc=%s ' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$output_path"
  free -b | awk '/^Mem:/ {printf "mem_available_bytes=%s ", $7} /^Swap:/ {printf "swap_used_bytes=%s\n", $3}' >>"$output_path"
  sleep 5
done

if wait "$stress_pid"; then
  echo "stress_status=passed" >>"$output_path"
else
  echo "stress_status=failed" >>"$output_path"
  cat "$output_path"
  exit 2
fi

echo "after=" >>"$output_path"
free -b >>"$output_path"
echo "swap_after=" >>"$output_path"
swapon --show >>"$output_path"
cat "$output_path"
