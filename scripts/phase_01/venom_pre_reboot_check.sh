#!/usr/bin/env bash
set -euo pipefail

# Final immediate gate before the one authorized controlled reboot.  This
# removes only the named temporary backup staging paths after restore proof;
# it never touches the durable evidence directory or the encrypted off-device
# copy on the TUF.
[[ "${EUID:-1}" -eq 0 ]] || { printf 'ROOT_REQUIRED\n' >&2; exit 1; }

for path in \
  /tmp/venom-phase1-config.tar.gz \
  /tmp/venom-phase1-config.tar.gz.sha256 \
  /tmp/venom-phase1-config.tar.gz.gpg \
  /tmp/venom-phase1-config-from-tuf.tar.gz.gpg \
  /tmp/venom-phase1-config-content \
  /tmp/venom_restore_config_backup.sh; do
  if [[ -d "$path" ]]; then
    rm -rf "$path"
  else
    rm -f "$path"
  fi
done

smart_health="$(smartctl -H /dev/sda 2>/dev/null || true)"
grep -Fq 'SMART overall-health self-assessment test result: PASSED' <<<"$smart_health"
smart_attributes="$(smartctl -A /dev/sda 2>/dev/null || true)"
awk '
  $1 == 5 || $1 == 197 || $1 == 198 {
    seen[$1] = 1
    if ($10 != 0) { bad = 1 }
  }
  END { exit !(seen[5] && seen[197] && seen[198] && !bad) }
' <<<"$smart_attributes"

sshd_effective="$(sshd -T)"
grep -Fxq 'permitrootlogin no' <<<"$sshd_effective"
grep -Fxq 'pubkeyauthentication yes' <<<"$sshd_effective"
grep -Fxq 'passwordauthentication yes' <<<"$sshd_effective"
sshd -t

ufw_output="$(ufw status verbose)"
grep -Eq '22/tcp[[:space:]]+ALLOW IN[[:space:]]+192\.162\.1\.0/24' <<<"$ufw_output"
! grep -Eq '22/tcp.*Anywhere' <<<"$ufw_output"

[[ -f /etc/systemd/journald.conf.d/90-venom-bounds.conf ]]
grep -Fq 'SystemMaxUse=256M' /etc/systemd/journald.conf.d/90-venom-bounds.conf
grep -Fq 'RuntimeMaxUse=128M' /etc/systemd/journald.conf.d/90-venom-bounds.conf
grep -Fq 'MaxRetentionSec=14day' /etc/systemd/journald.conf.d/90-venom-bounds.conf
journalctl --disk-usage

systemctl is-enabled --quiet venom-phase1-stability.timer
systemctl is-active --quiet venom-phase1-stability.timer
[[ -x /usr/local/lib/venom-phase1/venom_stability_monitor.sh ]]
for _ in 1 2 3 4; do
  systemctl start venom-phase1-stability.service
done
tail -n 1 /var/lib/venom-phase1/evidence/stability.csv
awk -F, 'NR > 1 { latest = $14 } END { exit !(latest == "passed") }' \
  /var/lib/venom-phase1/evidence/stability.csv

if systemctl --failed --no-legend --plain | grep -q '[^[:space:]]'; then
  printf 'FAILED_SYSTEM_UNITS_PRESENT\n' >&2
  exit 1
fi
[[ -z "$(docker ps -q)" ]]

printf 'PRE_REBOOT_ALL_GATES_PASS\n'
printf 'CONTROLLED_REBOOT_REQUESTED\n'
sync
systemctl reboot
