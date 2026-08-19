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
if [ ! -d "$release/.git" ]; then
    install -d -m 0755 "$install_root/releases"
    git clone --filter=blob:none --no-checkout "$repository_url" "$release"
fi
git -C "$release" fetch --filter=blob:none origin "$commit"
git -C "$release" checkout --detach "$commit"
deployed=$(git -C "$release" rev-parse HEAD)
[ "$deployed" = "$commit" ] || { echo 'ERROR=exact commit verification failed' >&2; exit 1; }

python3 -m venv "$install_root/venv"
"$install_root/venv/bin/python" -m pip install --disable-pip-version-check \
    'pydantic==2.13.4' 'pydantic-settings==2.14.2'
ln -sfn "$release" "$install_root/current"
chown -h venom:venom "$install_root/current"
install -d -o venom -g venom -m 0750 "$state_root"

install -m 0755 "$release/infrastructure/home_server/systemd/bmo-phase5b-tunnel-session" \
    /usr/local/lib/bmo-phase5b-tunnel-session
install -m 0644 "$release/infrastructure/home_server/systemd/bmo-phase5b-gateway-probe.service" \
    /etc/systemd/system/bmo-phase5b-gateway-probe.service
install -m 0644 "$release/infrastructure/home_server/systemd/bmo-phase5b-gateway-probe.timer" \
    /etc/systemd/system/bmo-phase5b-gateway-probe.timer

install -d -o venom -g venom -m 0700 /home/venom/.ssh
touch /home/venom/.ssh/authorized_keys
chown venom:venom /home/venom/.ssh/authorized_keys
chmod 0600 /home/venom/.ssh/authorized_keys
marker='bmo-phase05b-tunnel'
temporary=$(mktemp)
grep -v "$marker" /home/venom/.ssh/authorized_keys > "$temporary" || true
printf '%s %s %s\n' \
    'from="192.162.1.2",restrict,port-forwarding,permitlisten="127.0.0.1:11434",command="/usr/local/lib/bmo-phase5b-tunnel-session"' \
    "$public_key" "$marker" >> "$temporary"
install -o venom -g venom -m 0600 "$temporary" /home/venom/.ssh/authorized_keys
rm -f "$temporary"

systemctl daemon-reload
systemctl enable --now bmo-phase5b-gateway-probe.timer
systemctl start bmo-phase5b-gateway-probe.service
echo "PHASE_05B_VENOM_INSTALL_PASS commit=$deployed"
