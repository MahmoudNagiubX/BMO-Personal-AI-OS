#!/usr/bin/env bash
# BMO Personal AI OS - Lenovo Control Plane bootstrap preparation.
# This script is intended for the physically verified Lenovo only.

set -euo pipefail

readonly MIN_FREE_KB=10485760
readonly SSH_CONFIG=/etc/ssh/sshd_config.d/99-bmo-hardening.conf
readonly DOCKER_KEYRING=/etc/apt/keyrings/docker.asc
readonly DOCKER_SOURCE=/etc/apt/sources.list.d/docker.list
readonly DOCKER_CONFIG=/etc/docker/daemon.json

SSH_CANDIDATE=""
DOCKER_KEY_CANDIDATE=""
DOCKER_SOURCE_CANDIDATE=""
DOCKER_CONFIG_CANDIDATE=""
LAST_BACKUP=""

info() {
    printf 'INFO: %s\n' "$*"
}

warn() {
    printf 'WARN: %s\n' "$*" >&2
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    [[ -z "$SSH_CANDIDATE" ]] || rm -f -- "$SSH_CANDIDATE"
    [[ -z "$DOCKER_KEY_CANDIDATE" ]] || rm -f -- "$DOCKER_KEY_CANDIDATE"
    [[ -z "$DOCKER_SOURCE_CANDIDATE" ]] || rm -f -- "$DOCKER_SOURCE_CANDIDATE"
    [[ -z "$DOCKER_CONFIG_CANDIDATE" ]] || rm -f -- "$DOCKER_CONFIG_CANDIDATE"
}

trap cleanup EXIT

usage() {
    cat <<'EOF'
Usage:
  sudo ./bootstrap.sh --preflight
  BMO_LENOVO_BOOTSTRAP_CONFIRM=YES sudo -E ./bootstrap.sh --apply
  ./bootstrap.sh --help

--preflight  Read-only checks for the expected Lenovo environment.
--apply      Apply the prepared Lenovo baseline after explicit confirmation.
--help       Show this help text.

The script never identifies hardware from its hostname. Confirm the physical
Lenovo and complete the owner safety gate before using --apply.
EOF
}

command_available() {
    command -v "$1" >/dev/null 2>&1
}

check_tool() {
    local tool=$1
    if command_available "$tool"; then
        printf 'OK: tool available: %s\n' "$tool"
        return 0
    fi
    warn "expected tool is unavailable: $tool"
    return 1
}

check_platform() {
    local failures=0
    local os_id=''
    local kernel_name=''
    local machine=''
    local init_name=''

    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        os_id=${ID:-}
    fi

    if [[ "$os_id" == "ubuntu" ]]; then
        printf 'OK: operating system is Ubuntu (%s).\n' "${VERSION_ID:-unknown version}"
    else
        warn "operating system is not Ubuntu (detected: ${os_id:-unknown})"
        failures=1
    fi

    kernel_name=$(uname -s)
    machine=$(uname -m)
    if [[ "$kernel_name" != "Linux" ]]; then
        warn "unsupported kernel: $kernel_name"
        failures=1
    else
        printf 'OK: kernel is Linux.\n'
    fi

    case "$machine" in
        x86_64|amd64)
            printf 'OK: supported 64-bit architecture: %s.\n' "$machine"
            ;;
        *)
            warn "unsupported architecture: $machine"
            failures=1
            ;;
    esac

    if [[ -n "${WSL_INTEROP:-}" || -n "${WSL_DISTRO_NAME:-}" ]] || \
        { [[ -r /proc/version ]] && grep -Eqi 'microsoft|wsl' /proc/version; }; then
        warn 'WSL was detected; the physical Lenovo is required'
        failures=1
    fi

    if command_available systemctl && [[ -d /run/systemd/system ]]; then
        init_name=$(ps -p 1 -o comm= 2>/dev/null | tr -d '[:space:]')
        if [[ "$init_name" == "systemd" ]]; then
            printf 'OK: systemd is available and is PID 1.\n'
        else
            warn "systemd is not PID 1 (detected: ${init_name:-unknown})"
            failures=1
        fi
    else
        warn 'systemd is unavailable or its runtime directory is missing'
        failures=1
    fi

    return "$failures"
}

check_execution_identity() {
    if [[ "$(id -u)" -eq 0 ]]; then
        printf 'OK: running as root.\n'
    elif command_available sudo; then
        warn 'running without root; --apply must be run as root or through sudo'
    else
        warn 'running without root and sudo is unavailable'
    fi
}

check_endpoint() {
    local label=$1
    local host=$2
    local url=$3
    local failures=0

    if command_available getent && getent hosts "$host" >/dev/null 2>&1; then
        printf 'OK: DNS resolves %s.\n' "$host"
    else
        warn "DNS lookup failed for $label ($host)"
        failures=1
    fi

    if command_available curl && \
        curl -fsSL --max-time 10 --output /dev/null "$url"; then
        printf 'OK: HTTPS reaches %s.\n' "$url"
    else
        warn "HTTPS reachability check failed for $label ($url)"
        failures=1
    fi

    return "$failures"
}

check_network() {
    local failures=0
    check_endpoint 'official Ubuntu packages' 'archive.ubuntu.com' \
        'https://archive.ubuntu.com/ubuntu/' || failures=1
    check_endpoint 'official Docker packages' 'download.docker.com' \
        'https://download.docker.com/linux/ubuntu/gpg' || failures=1
    return "$failures"
}

check_disk_space() {
    local available_kb=''
    if ! command_available df || ! command_available awk; then
        warn 'cannot inspect available disk space because df or awk is unavailable'
        return 0
    fi

    available_kb=$(df -Pk / | awk 'NR == 2 { print $4 }')
    if [[ "$available_kb" =~ ^[0-9]+$ ]]; then
        printf 'INFO: available disk space on /: %s KiB.\n' "$available_kb"
        if (( available_kb >= MIN_FREE_KB )); then
            printf 'OK: available disk space meets the %s KiB preparation threshold.\n' \
                "$MIN_FREE_KB"
            return 0
        fi
    fi

    warn 'available disk space is below the preparation threshold or could not be read'
    return 1
}

check_ssh_state() {
    local state='unavailable'
    if command_available systemctl; then
        state=$(systemctl is-active ssh.service 2>/dev/null || true)
    fi
    printf 'INFO: SSH service state: %s.\n' "$state"
    if [[ "$state" == "active" ]]; then
        printf 'OK: SSH service is available.\n'
    else
        warn 'SSH service is not active; --apply will install the server package'
    fi
}

check_ufw_state() {
    if ! command_available ufw; then
        warn 'UFW is not installed; --apply will install it'
        return 0
    fi
    printf '%s\n' 'INFO: current UFW status (read-only):'
    ufw status verbose 2>&1 || true
}

check_docker_state() {
    local state='unavailable'
    if command_available systemctl; then
        state=$(systemctl is-active docker.service 2>/dev/null || true)
    fi
    printf 'INFO: Docker service state: %s.\n' "$state"
    if command_available docker; then
        if docker info >/dev/null 2>&1; then
            printf 'OK: Docker daemon responds to docker info.\n'
        else
            warn 'Docker command exists but the daemon did not answer docker info'
        fi
    else
        warn 'Docker is not installed; --apply will install it'
    fi
}

check_swap_state() {
    if command_available swapon; then
        printf '%s\n' 'INFO: current swap state (read-only):'
        swapon --show --bytes 2>&1 || true
    else
        warn 'swapon is unavailable; existing swap could not be inspected'
    fi
}

check_expected_tools() {
    local tool=''
    local expected_tools=(
        apt-get dpkg install curl gpg jq ufw systemctl sshd timedatectl
        df swapon getent awk cmp mktemp git unzip smartctl sensors
    )
    for tool in "${expected_tools[@]}"; do
        check_tool "$tool" || true
    done
}

run_preflight() {
    local failures=0
    info 'Lenovo bootstrap preflight is read-only.'
    check_platform || failures=1
    check_execution_identity
    check_network || failures=1
    check_disk_space || failures=1
    check_ssh_state
    check_ufw_state
    check_docker_state
    check_swap_state
    check_expected_tools

    if (( failures > 0 )); then
        warn 'Preflight found one or more blocking environment checks.'
        return 1
    fi
    info 'Preflight completed; review warnings and owner hardware evidence before --apply.'
}

require_apply_environment() {
    [[ "${BMO_LENOVO_BOOTSTRAP_CONFIRM:-}" == 'YES' ]] || \
        die 'refusing --apply; set BMO_LENOVO_BOOTSTRAP_CONFIRM=YES explicitly'
    [[ "$(id -u)" -eq 0 ]] || die '--apply must run as root'
    check_platform || die 'unsupported execution environment; the physical Lenovo is required'
    check_disk_space || die 'available disk space is insufficient for --apply'
    command_available apt-get || die 'apt-get is required for --apply'
    command_available dpkg || die 'dpkg is required for --apply'
}

backup_existing_if_changed() {
    local existing=$1
    local candidate=$2
    LAST_BACKUP=''

    if [[ -e "$existing" ]] && ! cmp -s "$existing" "$candidate"; then
        LAST_BACKUP="${existing}.bmo-backup-$(date -u +%Y%m%dT%H%M%SZ)"
        if [[ -e "$LAST_BACKUP" ]]; then
            LAST_BACKUP="${LAST_BACKUP}-$$"
        fi
        cp -p -- "$existing" "$LAST_BACKUP"
        info "Backed up changed configuration to $LAST_BACKUP"
    fi
}

apply_ssh_configuration() {
    local ssh_changed=0
    SSH_CANDIDATE=$(mktemp)
    cat > "$SSH_CANDIDATE" <<'EOF'
# BMO control plane SSH baseline
PermitRootLogin no
PubkeyAuthentication yes
EOF

    install -d -m 0755 /etc/ssh/sshd_config.d
    if cmp -s "$SSH_CANDIDATE" "$SSH_CONFIG" 2>/dev/null; then
        info 'SSH managed drop-in is already current.'
    else
        backup_existing_if_changed "$SSH_CONFIG" "$SSH_CANDIDATE"
        install -m 0644 "$SSH_CANDIDATE" "$SSH_CONFIG"
        ssh_changed=1
    fi

    if ! sshd -t; then
        if (( ssh_changed > 0 )); then
            if [[ -n "$LAST_BACKUP" ]]; then
                install -m 0644 "$LAST_BACKUP" "$SSH_CONFIG"
            else
                rm -f -- "$SSH_CONFIG"
            fi
        fi
        die 'sshd syntax validation failed; SSH was not restarted'
    fi

    if systemctl is-active --quiet ssh.service && (( ssh_changed > 0 )); then
        systemctl try-restart ssh.service
    elif ! systemctl is-active --quiet ssh.service; then
        systemctl start ssh.service
    fi
    info 'SSH configuration validated and service transition completed without closing existing sessions.'
}

apply_ufw_configuration() {
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow OpenSSH
    printf '%s\n' 'INFO: UFW rules before non-interactive enable:'
    ufw status numbered
    ufw --force enable
    printf '%s\n' 'INFO: UFW rules after enable:'
    ufw status numbered
}

apply_docker_repository() {
    local ubuntu_codename=''
    local dpkg_architecture=''

    install -d -m 0755 /etc/apt/keyrings
    DOCKER_KEY_CANDIDATE=$(mktemp)
    curl -fsSL 'https://download.docker.com/linux/ubuntu/gpg' \
        --output "$DOCKER_KEY_CANDIDATE"
    [[ -s "$DOCKER_KEY_CANDIDATE" ]] || die 'Docker signing key download was empty'
    if cmp -s "$DOCKER_KEY_CANDIDATE" "$DOCKER_KEYRING" 2>/dev/null; then
        info 'Docker signing key is already current.'
    else
        install -m 0644 "$DOCKER_KEY_CANDIDATE" "$DOCKER_KEYRING"
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    ubuntu_codename=${VERSION_CODENAME:-}
    [[ -n "$ubuntu_codename" ]] || die 'Ubuntu VERSION_CODENAME is missing'
    dpkg_architecture=$(dpkg --print-architecture)
    [[ -n "$dpkg_architecture" ]] || die 'dpkg architecture is missing'

    DOCKER_SOURCE_CANDIDATE=$(mktemp)
    printf 'deb [arch=%s signed-by=%s] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$dpkg_architecture" "$DOCKER_KEYRING" "$ubuntu_codename" \
        > "$DOCKER_SOURCE_CANDIDATE"
    if cmp -s "$DOCKER_SOURCE_CANDIDATE" "$DOCKER_SOURCE" 2>/dev/null; then
        info 'Docker apt source is already current.'
    else
        install -d -m 0755 /etc/apt/sources.list.d
        backup_existing_if_changed "$DOCKER_SOURCE" "$DOCKER_SOURCE_CANDIDATE"
        install -m 0644 "$DOCKER_SOURCE_CANDIDATE" "$DOCKER_SOURCE"
    fi

    apt-get update -qq
    apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

apply_docker_configuration() {
    local docker_tcp_prefix=''
    local docker_config_changed=0
    DOCKER_CONFIG_CANDIDATE=$(mktemp)
    if [[ -f "$DOCKER_CONFIG" ]]; then
        jq -e 'type == "object"' "$DOCKER_CONFIG" >/dev/null || \
            die 'existing /etc/docker/daemon.json is not a JSON object; refusing to replace it'
        jq -e '(."log-opts" == null) or (."log-opts" | type == "object")' \
            "$DOCKER_CONFIG" >/dev/null || \
            die 'existing Docker log-opts is not a JSON object; refusing to replace it'
        docker_tcp_prefix=$(printf '%s%s' 'tcp' '://')
        jq -e --arg prefix "$docker_tcp_prefix" \
            '(.hosts // []) | map(select(type == "string" and startswith($prefix))) | length == 0' \
            "$DOCKER_CONFIG" >/dev/null || \
            die 'existing Docker configuration exposes a TCP host; refusing to preserve it'
        jq '."log-driver" = "json-file" | ."log-opts" = ((."log-opts" // {}) + {"max-size":"10m","max-file":"3"})' \
            "$DOCKER_CONFIG" > "$DOCKER_CONFIG_CANDIDATE"
    else
        jq -n '{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}' \
            > "$DOCKER_CONFIG_CANDIDATE"
    fi

    jq -e 'type == "object" and ."log-driver" == "json-file" and ."log-opts"."max-size" == "10m" and ."log-opts"."max-file" == "3"' \
        "$DOCKER_CONFIG_CANDIDATE" >/dev/null || die 'generated Docker daemon configuration failed JSON validation'

    install -d -m 0755 /etc/docker
    if cmp -s "$DOCKER_CONFIG_CANDIDATE" "$DOCKER_CONFIG" 2>/dev/null; then
        info 'Docker daemon logging configuration is already current.'
    else
        backup_existing_if_changed "$DOCKER_CONFIG" "$DOCKER_CONFIG_CANDIDATE"
        install -m 0644 "$DOCKER_CONFIG_CANDIDATE" "$DOCKER_CONFIG"
        docker_config_changed=1
    fi

    systemctl enable docker.service
    if ! systemctl is-active --quiet docker.service; then
        systemctl start docker.service
    elif (( docker_config_changed > 0 )); then
        systemctl try-restart docker.service
    fi
    docker info >/dev/null
    docker run --rm hello-world >/dev/null
    docker image rm hello-world:latest >/dev/null 2>&1 || true
    info 'Docker daemon configuration validated and Docker health checks completed.'
}

run_apply() {
    require_apply_environment
    export DEBIAN_FRONTEND=noninteractive

    apt-get update -qq
    apt-get install -y -qq \
        ca-certificates curl gnupg git jq lm-sensors smartmontools unzip ufw openssh-server
    check_network || die 'network and DNS checks must pass before Docker setup'
    timedatectl set-timezone Africa/Cairo

    apply_ssh_configuration
    apply_ufw_configuration
    apply_docker_repository
    apply_docker_configuration

    info 'Bootstrap configuration completed. Reboot and hardware acceptance checks are still required.'
}

main() {
    local mode=${1:-}
    case "$mode" in
        --help|-h)
            usage
            ;;
        --preflight)
            [[ "$#" -eq 1 ]] || die '--preflight does not accept additional arguments'
            run_preflight
            ;;
        --apply)
            [[ "$#" -eq 1 ]] || die '--apply does not accept additional arguments'
            run_apply
            ;;
        *)
            usage >&2
            die 'choose --preflight, --apply, or --help'
            ;;
    esac
}

main "$@"
