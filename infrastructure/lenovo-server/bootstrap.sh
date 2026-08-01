#!/usr/bin/env bash
# BMO Personal AI OS — Lenovo Control Plane Baseline Bootstrap
# This script sets up Ubuntu Server 24.04 LTS baseline, SSH hardening, UFW firewall, and Docker Engine.
# Do NOT run this script on desktop or non-control-plane systems without reviewing.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root or with sudo." >&2
    exit 1
fi

echo "==> Updating package indices and upgrading existing packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get full-upgrade -y -qq

echo "==> Installing baseline diagnostic and administration utilities..."
apt-get install -y -qq \
    smartmontools \
    lm-sensors \
    curl \
    ca-certificates \
    gnupg \
    git \
    jq \
    unzip \
    ufw

echo "==> Setting timezone to Africa/Cairo..."
timedatectl set-timezone Africa/Cairo

echo "==> Configuring SSH hardening drop-in..."
mkdir -p /etc/ssh/sshd_config.d
cat <<'EOF' > /etc/ssh/sshd_config.d/99-bmo-hardening.conf
# Hardened SSH configuration for BMO control plane
PermitRootLogin no
PubkeyAuthentication yes
EOF

chmod 644 /etc/ssh/sshd_config.d/99-bmo-hardening.conf
sshd -t
systemctl restart ssh

echo "==> Configuring UFW firewall baseline..."
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "==> Setting up official Docker apt repository..."
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
fi

UBUNTU_CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
cat <<EOF > /etc/apt/sources.list.d/docker.list
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME} stable
EOF

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Hardening Docker daemon logging configuration..."
mkdir -p /etc/docker
cat <<'EOF' > /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

chmod 644 /etc/docker/daemon.json
systemctl enable --now docker
systemctl restart docker

echo "==> Verifying Docker baseline..."
docker --version
docker compose version
docker info > /dev/null

echo "==> Lenovo Control Plane Baseline Bootstrap Completed Successfully!"
