#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo 'ERROR=run this reviewed installer with sudo' >&2
    exit 1
fi
if [ "$#" -ne 3 ]; then
    echo 'usage: install_venom.sh <40-char-commit> <tunnel-public-key-file> <repository-url>' >&2
    exit 2
fi

commit=$1
public_key_file=$2
repository_url=$3
case "$commit" in
    *[!0-9a-f]*|'') echo 'ERROR=invalid exact commit' >&2; exit 2 ;;
esac
if [ "${#commit}" -ne 40 ] || [ ! -f "$public_key_file" ]; then
    echo 'ERROR=invalid commit or missing public key file' >&2
    exit 2
fi
public_key=$(tr -d '\r\n' < "$public_key_file")
case "$public_key" in
    'ssh-ed25519 '*|'sk-ssh-ed25519@openssh.com '*) ;;
    *) echo 'ERROR=unexpected tunnel public key type' >&2; exit 2 ;;
esac

install_root=/opt/bmo-phase5b
release="$install_root/releases/$commit"
state_root=/var/lib/bmo-phase5b
tunnel_user=bmo-tunnel
tunnel_home=/var/lib/bmo-phase5b-tunnel
match_config=/etc/ssh/sshd_config.d/91-bmo-phase5b-tunnel.conf
admin_authorized_keys=/home/venom/.ssh/authorized_keys
tunnel_authorized_keys="$tunnel_home/.ssh/authorized_keys"
marker=bmo-phase05b-tunnel
backup_root="$state_root/security-recovery-backup-$commit"
created_user=0
rollback_ready=0
completed=0

rollback() {
    if [ -f "$backup_root/admin_authorized_keys" ]; then
        install -o venom -g venom -m 0600 "$backup_root/admin_authorized_keys" \
            "$admin_authorized_keys"
    fi
    if [ -f "$backup_root/match_config" ]; then
        install -o root -g root -m 0644 "$backup_root/match_config" "$match_config"
    else
        rm -f "$match_config"
    fi
    if [ "$created_user" -eq 1 ]; then
        userdel -r "$tunnel_user" >/dev/null 2>&1 || true
    elif [ -f "$backup_root/tunnel_authorized_keys" ]; then
        install -d -o "$tunnel_user" -g "$tunnel_user" -m 0700 "$tunnel_home/.ssh"
        install -o "$tunnel_user" -g "$tunnel_user" -m 0600 \
            "$backup_root/tunnel_authorized_keys" "$tunnel_authorized_keys"
    fi
    if [ -f "$backup_root/previous_release" ]; then
        previous_release=$(cat "$backup_root/previous_release")
        if [ -n "$previous_release" ] && [ -d "$previous_release" ]; then
            ln -sfn "$previous_release" "$install_root/current"
            chown -h venom:venom "$install_root/current"
        fi
    fi
    if [ -f "$backup_root/deployed-commit" ]; then
        install -o root -g root -m 0644 "$backup_root/deployed-commit" \
            "$install_root/deployed-commit"
    fi
    /usr/sbin/sshd -t >/dev/null 2>&1 && systemctl reload ssh >/dev/null 2>&1 || true
}

cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    if [ "$rollback_ready" -eq 1 ] && [ "$completed" -ne 1 ]; then
        rollback
        echo 'PHASE_05B_SECURITY_INSTALL_ROLLED_BACK' >&2
    fi
    exit "$rc"
}
trap cleanup EXIT HUP INT TERM

install -d -m 0755 "$install_root/releases"
if [ ! -d "$release/.git" ]; then
    git clone --filter=blob:none --no-checkout "$repository_url" "$release"
fi
git -C "$release" fetch --filter=blob:none origin "$commit"
git -C "$release" checkout --detach "$commit"
deployed=$(git -C "$release" rev-parse HEAD)
[ "$deployed" = "$commit" ] || { echo 'ERROR=exact commit verification failed' >&2; exit 1; }

python3 -m venv "$install_root/venv"
"$install_root/venv/bin/python" -m pip install --disable-pip-version-check \
    'pydantic==2.13.4' 'pydantic-settings==2.14.2'

install -d -o venom -g venom -m 0700 /home/venom/.ssh
touch "$admin_authorized_keys"
chown venom:venom "$admin_authorized_keys"
chmod 0600 "$admin_authorized_keys"
install -d -o root -g root -m 0700 "$backup_root"
if [ -f "$admin_authorized_keys" ]; then
    cp -p "$admin_authorized_keys" "$backup_root/admin_authorized_keys"
fi
if [ -f "$match_config" ]; then
    cp -p "$match_config" "$backup_root/match_config"
fi
if [ -f "$tunnel_authorized_keys" ]; then
    cp -p "$tunnel_authorized_keys" "$backup_root/tunnel_authorized_keys"
fi
if [ -L "$install_root/current" ]; then
    readlink -f "$install_root/current" > "$backup_root/previous_release"
fi
if [ -f "$install_root/deployed-commit" ]; then
    cp -p "$install_root/deployed-commit" "$backup_root/deployed-commit"
fi
rollback_ready=1

admin_policy_before=$(/usr/sbin/sshd -T -C user=venom,host=venom-server,addr=192.162.1.2 |
    grep -E '^(allowtcpforwarding|permitopen|permitlisten|permittty|x11forwarding|allowagentforwarding|passwordauthentication|kbdinteractiveauthentication|forcecommand) ')

install -m 0755 "$release/infrastructure/home_server/systemd/bmo-phase5b-tunnel-session" \
    /usr/local/lib/bmo-phase5b-tunnel-session
install -m 0644 "$release/infrastructure/home_server/systemd/bmo-phase5b-gateway-probe.service" \
    /etc/systemd/system/bmo-phase5b-gateway-probe.service
install -m 0644 "$release/infrastructure/home_server/systemd/bmo-phase5b-gateway-probe.timer" \
    /etc/systemd/system/bmo-phase5b-gateway-probe.timer

if ! id "$tunnel_user" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$tunnel_home" --shell /bin/sh --user-group \
        "$tunnel_user"
    created_user=1
fi
usermod --home "$tunnel_home" --shell /bin/sh --password 'x' "$tunnel_user"
if id -nG "$tunnel_user" | tr ' ' '\n' | grep -qx sudo; then
    deluser "$tunnel_user" sudo >/dev/null
fi
privileged_groups=$(id -nG "$tunnel_user" | tr ' ' '\n' | grep -Ex 'sudo|adm|docker' || true)
if [ -n "$privileged_groups" ]; then
    echo 'ERROR=tunnel identity has a privileged or product group' >&2
    exit 1
fi

install -d -o "$tunnel_user" -g "$tunnel_user" -m 0700 "$tunnel_home/.ssh"
temporary=$(mktemp)
printf '%s %s %s\n' \
    'from="192.162.1.2",restrict,port-forwarding,permitlisten="127.0.0.1:11434",permitlisten="127.0.0.1:11435",command="/usr/local/lib/bmo-phase5b-tunnel-session"' \
    "$public_key" "$marker" > "$temporary"
install -o "$tunnel_user" -g "$tunnel_user" -m 0600 "$temporary" "$tunnel_authorized_keys"
rm -f "$temporary"

temporary=$(mktemp)
cat > "$temporary" <<'EOF'
Match User bmo-tunnel
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    AllowTcpForwarding remote
    PermitOpen none
    PermitListen 127.0.0.1:11434 127.0.0.1:11435
    GatewayPorts no
    ForceCommand /usr/local/lib/bmo-phase5b-tunnel-session
Match all
EOF
install -o root -g root -m 0644 "$temporary" "$match_config"
rm -f "$temporary"

/usr/sbin/sshd -t
effective=$(/usr/sbin/sshd -T -C user="$tunnel_user",host=venom-server,addr=192.162.1.2)
for expected in \
    'allowtcpforwarding remote' \
    'permitopen none' \
    'permitlisten 127.0.0.1:11434' \
    'permitlisten 127.0.0.1:11435' \
    'permittty no' \
    'x11forwarding no' \
    'allowagentforwarding no' \
    'passwordauthentication no' \
    'kbdinteractiveauthentication no' \
    'gatewayports no' \
    'pubkeyauthentication yes' \
    'authenticationmethods publickey' \
    'forcecommand /usr/local/lib/bmo-phase5b-tunnel-session'
do
    printf '%s\n' "$effective" | grep -Fqx "$expected" || {
        echo "ERROR=effective tunnel policy mismatch: $expected" >&2
        exit 1
    }
done

admin_policy_after=$(/usr/sbin/sshd -T -C user=venom,host=venom-server,addr=192.162.1.2 |
    grep -E '^(allowtcpforwarding|permitopen|permitlisten|permittty|x11forwarding|allowagentforwarding|passwordauthentication|kbdinteractiveauthentication|forcecommand) ')
[ "$admin_policy_before" = "$admin_policy_after" ] || {
    echo 'ERROR=normal venom administrator SSH policy changed' >&2
    exit 1
}
/usr/sbin/sshd -T -C user=root,host=venom-server,addr=192.162.1.2 |
    grep -Fqx 'permitrootlogin no' || {
        echo 'ERROR=root SSH is not denied' >&2
        exit 1
    }

temporary=$(mktemp)
grep -v "$marker" "$admin_authorized_keys" > "$temporary" || true
install -o venom -g venom -m 0600 "$temporary" "$admin_authorized_keys"
rm -f "$temporary"

systemctl reload ssh
systemctl daemon-reload
systemctl enable --now bmo-phase5b-gateway-probe.timer
ln -sfn "$release" "$install_root/current"
chown -h venom:venom "$install_root/current"
printf '%s\n' "$deployed" > "$install_root/deployed-commit"
chmod 0644 "$install_root/deployed-commit"
install -d -o venom -g venom -m 0750 "$state_root"
systemctl start bmo-phase5b-gateway-probe.service

completed=1
printf 'OPENSSH_VERSION='
/usr/sbin/sshd -V 2>&1
echo 'SSHD_CONFIG_TEST=pass'
echo 'TUNNEL_IDENTITY=bmo-tunnel'
echo 'ALLOW_TCP_FORWARDING=remote'
echo 'PERMIT_OPEN=none'
echo 'PERMIT_LISTEN=127.0.0.1:11434'
echo 'ADMIN_SSH_POLICY_UNCHANGED=true'
echo 'ROOT_SSH_DENIED=true'
echo "PHASE_05B_TUNNEL_SECURITY_INSTALL_PASS commit=$deployed"
