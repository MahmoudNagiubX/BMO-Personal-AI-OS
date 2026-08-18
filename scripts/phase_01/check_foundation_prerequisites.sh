#!/usr/bin/env bash
set -euo pipefail

# Read-only, bounded preflight for a human operator on the Lenovo. It writes
# nothing, makes no network connection, and does not replace the safety gate.

readonly COMMAND_TIMEOUT_SECONDS=5

run_read_only() {
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  if command -v timeout >/dev/null 2>&1; then
    timeout --foreground "${COMMAND_TIMEOUT_SECONDS}s" "$@" ||
      printf 'NOT_CAPTURED: %s\n' "$label"
  else
    "$@" || printf 'NOT_CAPTURED: %s\n' "$label"
  fi
}

run_read_only "identity" hostname
run_read_only "architecture" uname -m
run_read_only "cpu cores" nproc
run_read_only "operating system" cat /etc/os-release
run_read_only "memory" free -h
run_read_only "swap" swapon --show
run_read_only "root filesystem" findmnt -no SOURCE,FSTYPE,SIZE,AVAIL /
run_read_only "filesystem usage" df -hT /
run_read_only "block devices" lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL
run_read_only "network addresses" ip -br addr
run_read_only "default route" ip route show default
run_read_only "load" cat /proc/loadavg
run_read_only "uptime" uptime
run_read_only "failed services" systemctl --failed --no-legend

if command -v networkctl >/dev/null 2>&1; then
  run_read_only "network links" networkctl list --no-pager
fi
if command -v ethtool >/dev/null 2>&1; then
  printf '\n==> ethtool requires an operator-selected Ethernet interface; no interface is guessed.\n'
fi
if command -v sensors >/dev/null 2>&1; then
  run_read_only "thermal sensors" sensors
else
  printf '\n==> thermal sensors\nNOT_CAPTURED: sensors is not installed\n'
fi
if command -v ufw >/dev/null 2>&1; then
  run_read_only "firewall status" ufw status
fi
if command -v smartctl >/dev/null 2>&1; then
  run_read_only "system disk SMART health" smartctl -H /dev/sda
fi

printf '\nRead-only preflight complete. Review output and run the Phase 1 safety runbooks before any privileged change.\n'
