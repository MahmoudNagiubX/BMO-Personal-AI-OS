#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo 'ERROR=run this reviewed verifier with sudo' >&2
    exit 1
fi
if [ "$#" -ne 1 ]; then
    echo 'usage: verify_venom_security_closeout.sh <40-char-security-commit>' >&2
    exit 2
fi
commit=$1
case "$commit" in
    *[!0-9a-f]*|'') echo 'ERROR=invalid exact commit' >&2; exit 2 ;;
esac
[ "${#commit}" -eq 40 ] || { echo 'ERROR=invalid exact commit' >&2; exit 2; }

/usr/sbin/sshd -t
effective=$(/usr/sbin/sshd -T -C user=bmo-tunnel,host=venom-server,addr=192.162.1.2)
for expected in \
    'allowtcpforwarding remote' \
    'permitopen none' \
    'permitlisten 127.0.0.1:11434' \
    'permittty no' \
    'x11forwarding no' \
    'allowagentforwarding no' \
    'passwordauthentication no' \
    'kbdinteractiveauthentication no' \
    'gatewayports no' \
    'forcecommand /usr/local/lib/bmo-phase5b-tunnel-session'
do
    printf '%s\n' "$effective" | grep -Fqx "$expected" || {
        echo "ERROR=effective tunnel policy mismatch: $expected" >&2
        exit 1
    }
done
/usr/sbin/sshd -T -C user=venom,host=venom-server,addr=192.162.1.2 |
    grep -Fqx 'forcecommand none' || { echo 'ERROR=admin account has a forced command' >&2; exit 1; }
/usr/sbin/sshd -T -C user=root,host=venom-server,addr=192.162.1.2 |
    grep -Fqx 'permitrootlogin no' || { echo 'ERROR=root SSH is not denied' >&2; exit 1; }

[ "$(cat /opt/bmo-phase5b/deployed-commit)" = "$commit" ] || {
    echo 'ERROR=deployed commit mismatch' >&2
    exit 1
}
[ "$(grep -c bmo-phase05b-tunnel /home/venom/.ssh/authorized_keys || true)" -eq 0 ] || {
    echo 'ERROR=old admin tunnel authorization remains' >&2
    exit 1
}
[ "$(grep -c bmo-phase05b-tunnel /var/lib/bmo-phase5b-tunnel/.ssh/authorized_keys)" -eq 1 ] || {
    echo 'ERROR=dedicated tunnel authorization count is invalid' >&2
    exit 1
}
[ "$(id -nG bmo-tunnel)" = 'bmo-tunnel' ] || {
    echo 'ERROR=dedicated tunnel identity has unexpected groups' >&2
    exit 1
}

ufw_status=$(/usr/sbin/ufw status verbose)
printf '%s\n' "$ufw_status" | grep -Fqx 'Status: active' || {
    echo 'ERROR=UFW is not active' >&2
    exit 1
}
printf '%s\n' "$ufw_status" | grep -Eq '^Default: deny \(incoming\), allow \(outgoing\), deny \(routed\)$' || {
    echo 'ERROR=UFW defaults changed' >&2
    exit 1
}
ssh_rules=$(printf '%s\n' "$ufw_status" | grep '22/tcp' || true)
[ "$(printf '%s\n' "$ssh_rules" | grep -c '22/tcp')" -eq 1 ] || {
    printf 'SANITIZED_UFW_SSH_RULES=%s\n' "$ssh_rules" >&2
    echo 'ERROR=expected exactly one SSH UFW rule' >&2
    exit 1
}
case "$ssh_rules" in
    *'22/tcp'*'ALLOW IN'*'192.162.1.0/24'*) ;;
    *)
        printf 'SANITIZED_UFW_SSH_RULES=%s\n' "$ssh_rules" >&2
        echo 'ERROR=scoped SSH UFW rule is missing' >&2
        exit 1
        ;;
esac
if printf '%s\n' "$ufw_status" | grep -q '11434'; then
    echo 'ERROR=UFW contains an Ollama rule' >&2
    exit 1
fi

listeners=$(ss -lnt '( sport = :11434 )')
printf '%s\n' "$listeners" | grep -Eq '127\.0\.0\.1:11434' || {
    echo 'ERROR=VENOM loopback listener is missing' >&2
    exit 1
}
if printf '%s\n' "$listeners" | grep -Eq '0\.0\.0\.0:11434|\[::\]:11434|192\.162\.1\.21:11434'; then
    echo 'ERROR=VENOM has a non-loopback Ollama listener' >&2
    exit 1
fi

failed_units=$(systemctl --failed --no-legend --plain | wc -l)
[ "$failed_units" -eq 0 ] || { echo 'ERROR=failed systemd units present' >&2; exit 1; }
latest=$(tail -n 1 /var/lib/venom-phase1/evidence/stability.csv)
phase1=$(printf '%s\n' "$latest" | awk -F, '{
    printf "timestamp_utc=%s temperature_c=%s root_used_percent=%s failed_units=%s smart_status=%s smart_sectors=%s/%s/%s ssh=%s ufw=%s",
        $1, $10, $9, $13, $14, $15, $16, $17, $18, $19
}')
printf '%s\n' "$phase1" | grep -Eq \
    'failed_units=0 smart_status=passed smart_sectors=0/0/0 ssh=active ufw=active$' || {
        echo 'ERROR=latest Phase 1 sample is not healthy' >&2
        exit 1
    }

echo 'SSHD_CONFIG_TEST=pass'
echo 'TUNNEL_IDENTITY=bmo-tunnel'
echo 'DIRECTIONAL_FORWARDING_POLICY=remote_only'
echo 'ADMIN_SSH_POLICY_UNCHANGED=true'
echo 'ROOT_SSH_DENIED=true'
echo 'UFW_ACTIVE=true'
echo 'UFW_DEFAULT_INCOMING=deny'
echo 'UFW_SSH_SCOPE=192.162.1.0/24'
echo 'UFW_OLLAMA_RULE=false'
echo 'VENOM_11434_LOOPBACK_ONLY=true'
echo "FAILED_UNITS=$failed_units"
echo "PHASE_1_LATEST_PASS $phase1"
echo "PHASE_05B_SECURITY_CLOSEOUT_PASS commit=$commit"
