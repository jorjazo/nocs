#!/bin/bash
# Lab Pi setup, run as root by nocs-lab-setup.service until it succeeds once.
# It is idempotent: every step checks whether it is already done, so a run
# interrupted by a missing network simply resumes at the next boot or retry.
# Settings come from /etc/nocs-lab.env (PI_USER, NOCS_REPO, WITH_ASTAP).
set -euo pipefail
source /etc/nocs-lab.env

READY=/var/lib/nocs-lab/ready
ASTAP_CLI_URL=https://sourceforge.net/projects/astap-program/files/linux_installer/astap_command-line_version_Linux_aarch64.zip/download
ASTAP_DB_URL=https://sourceforge.net/projects/astap-program/files/star_databases/d50_star_database.deb/download
home=$(getent passwd "$PI_USER" | cut -d: -f6)
as_user() { sudo -u "$PI_USER" -H "$@"; }
# Resume partial downloads. SourceForge mirrors serve a fresh connection fast and
# then throttle it hard, so give up as soon as it drops below 1 MB/s; the
# service's retry resumes on a new, fast connection.
download() { curl -fsSL -C - --speed-limit 1000000 --speed-time 20 -o "$1" "$2"; }

# Fail fast (and retry later) instead of half-installing without a network.
getent hosts archive.ubuntu.com >/dev/null || { echo "no network yet"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y avahi-daemon curl docker-compose-v2 docker.io git python3 unzip
apt-get upgrade -y
usermod -aG docker "$PI_USER"

[[ -x $home/.local/bin/uv ]] || as_user sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
[[ -d $home/nocs/.git ]] || as_user git clone "$NOCS_REPO" "$home/nocs"

if [[ ${WITH_ASTAP:-1} == 1 ]]; then
    mkdir -p /opt/astap
    if [[ ! -x /opt/astap/astap_cli ]]; then
        download /tmp/astap_cli.zip "$ASTAP_CLI_URL"
        unzip -o /tmp/astap_cli.zip -d /opt/astap
        chmod +x /opt/astap/astap_cli
    fi
    if [[ ! -f /opt/astap/.d50-installed ]]; then
        download /tmp/d50.deb "$ASTAP_DB_URL"
        dpkg -i /tmp/d50.deb
        touch /opt/astap/.d50-installed
    fi
fi

mkdir -p "$(dirname "$READY")"
date -Is > "$READY"
echo "NOCS lab setup complete"
