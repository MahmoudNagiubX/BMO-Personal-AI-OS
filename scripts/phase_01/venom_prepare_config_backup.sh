#!/usr/bin/env bash
set -euo pipefail

# Prepare a small, configuration-only archive. Encryption and transfer are
# intentionally separate interactive operations and are never scripted here.

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run this script through sudo.\n' >&2
  exit 1
fi

readonly archive=/tmp/venom-phase1-config.tar.gz
readonly checksum=/tmp/venom-phase1-config.tar.gz.sha256
readonly stage=/tmp/venom-phase1-config-content

rm -f "$archive" "$checksum"
rm -rf "$stage"
install -d -m 0700 "$stage"

copy_file() {
  local source="$1"
  local relative="$2"
  if [[ -f "$source" ]]; then
    install -D -m 0644 "$source" "$stage/$relative"
  fi
}

copy_file /etc/hostname etc/hostname
copy_file /etc/hosts etc/hosts
copy_file /etc/ssh/sshd_config etc/ssh/sshd_config
copy_file /etc/ssh/sshd_config.d/90-venom-phase1.conf etc/ssh/sshd_config.d/90-venom-phase1.conf
copy_file /etc/ufw/user.rules etc/ufw/user.rules
copy_file /etc/ufw/user6.rules etc/ufw/user6.rules
copy_file /etc/systemd/journald.conf.d/90-venom-bounds.conf etc/systemd/journald.conf.d/90-venom-bounds.conf
copy_file /etc/systemd/system/venom-phase1-stability.service etc/systemd/system/venom-phase1-stability.service
copy_file /etc/systemd/system/venom-phase1-stability.timer etc/systemd/system/venom-phase1-stability.timer

{
  printf 'backup_scope=configuration_only\n'
  printf 'hostname=%s\n' "$(hostname)"
  printf 'ip_addresses=\n'
  ip -br addr
  printf 'default_routes=\n'
  ip route show default
  printf 'ufw_status=\n'
  ufw status numbered
  printf 'ssh_effective=\n'
  sshd -T | grep -E '^(port|permitrootlogin|passwordauthentication|pubkeyauthentication)'
  printf 'enabled_phase1_units=\n'
  systemctl is-enabled venom-phase1-stability.timer
  systemctl is-active venom-phase1-stability.timer
  printf 'package_inventory=dpkg-query\n'
  dpkg-query -W -f='${Package}\t${Version}\n'
} >"$stage/recovery-manifest.txt"

find "$stage" -type f -printf '%P\n' | sort >"$stage/file-manifest.txt"
tar -C "$stage" -czf "$archive" .
sha256sum "$archive" >"$checksum"

printf 'ARCHIVE=%s\nCHECKSUM=%s\nCONTENTS=\n' "$archive" "$checksum"
cat "$stage/file-manifest.txt"
printf 'PLAINTEXT_ARCHIVE_REMAINS_ON_VENOM_UNTIL_RESTORE_PROOF\n'
