#!/usr/bin/env bash
# Install a nocs .deb on a clean Ubuntu 26.04 with systemd running, and check that
# its services come up: nocsd answers, is connected to indiserver, starts a driver
# through the FIFO, reaches nocs-system (which reboots nothing on a PC), and PHD2
# listens (ADR 0025, ADR 0027). Given nocs-appliance too, it then installs it and
# checks that the box became the appliance: the firewall, nocsd on port 80, every
# operation of nocs-system, the SMB share switched on and off.
#
#   packaging/deb/test.sh packaging/out/nocs_<version>_<arch>.deb [nocs-appliance_<version>_all.deb]
#
# The container runs systemd, so it needs --privileged. PLATFORM as in build.sh.
set -euo pipefail

deb=$(realpath "${1:?usage: $0 <nocs .deb>}")
platform=()
[[ -n ${PLATFORM:-} ]] && platform=(--platform "$PLATFORM")
name=nocs-deb-test-$$
context=$(mktemp -d)
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$context"' EXIT

appliance=${2:+$(realpath "$2")}
cp "$deb" "$context/"
mkdir -p "$context/appliance"
[[ -n $appliance ]] && cp "$appliance" "$context/appliance/"
cat > "$context/Containerfile" <<'CONTAINERFILE'
FROM ubuntu:26.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends systemd systemd-sysv dbus curl \
        ca-certificates software-properties-common gpg-agent \
    && add-apt-repository -y ppa:mutlaqja/ppa \
    && add-apt-repository -y ppa:pch/phd2
# Not in /tmp, which systemd mounts empty when it runs.
COPY *.deb /debs/
COPY appliance/ /debs/appliance/
# Without systemd running, the package enables nocsd but starts nothing.
RUN apt-get install -y /debs/*.deb phd2 xvfb
# Docker's images forbid starting services (exit 101); a real system does not.
RUN rm /usr/sbin/policy-rc.d
CMD ["/sbin/init"]
CONTAINERFILE
docker build "${platform[@]}" -t nocs-deb-test -f "$context/Containerfile" "$context"
docker run -d "${platform[@]}" --name "$name" --privileged --cgroupns=host \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw --tmpfs /run --tmpfs /run/lock nocs-deb-test >/dev/null

check() {
    docker exec -i "$name" bash -s <<'CHECK'
set -euo pipefail
fail() { echo "FAIL: $*"; systemctl status --no-pager nocsd nocs-indiserver nocs-phd2 || true; journalctl --no-pager -n 60 -u nocsd -u nocs-indiserver -u nocs-phd2; exit 1; }
health() { curl -fsS -H 'Host: localhost' http://127.0.0.1:8000/api/health; }
for _ in $(seq 120); do health 2>/dev/null | grep -q '"indi_connected":true' && break; sleep 1; done
health | grep -q '"indi_connected":true' || fail "nocsd does not answer, or is not connected to indiserver"
echo "health: $(health)"
for unit in nocsd nocs-indiserver nocs-phd2 nocs-system; do
    [[ $(systemctl is-active "$unit") == active ]] || fail "$unit is not active"
done
[[ $(systemctl is-enabled nocsd) == enabled ]] || fail "nocsd is not enabled"
[[ $(stat -c %U /var/lib/nocs /var/lib/nocs/config) == $'nocs\nnocs' ]] || fail "/var/lib/nocs is not nocs's"
id -nG nocs | grep -qw dialout || fail "nocs is not in dialout"
curl -fsS -H 'Host: localhost' http://127.0.0.1:8000/ | grep -q '<div id="app">' || fail "no web app"
# nocs-system answers nocs, nocsd reaches it, and on a PC it performs nothing.
runuser -u nocs -- /opt/nocs/venv/bin/nocs-system call hello | grep -q '"operations": \["services.restart"\]' \
    || fail "nocs-system does not answer nocs, or performs more than restarting services on a PC"
# nocsd runs under systemd's watchdog (Type=notify): it said it is ready, and keeps it fed.
[[ $(systemctl show -p WatchdogUSec --value nocsd) == 30s ]] || fail "nocsd is not watched"
api=(-H 'Host: localhost' -b /tmp/jar -c /tmp/jar)
curl -fsS "${api[@]}" -H 'Content-Type: application/json' \
    -d '{"passphrase": "test passphrase", "name": "test"}' http://127.0.0.1:8000/api/auth/setup >/dev/null
for _ in $(seq 15); do
    curl -fsS "${api[@]}" http://127.0.0.1:8000/api/state | grep -q '"helper":true' && break
    sleep 1
done
curl -fsS "${api[@]}" http://127.0.0.1:8000/api/state | grep -q '"helper":true' || fail "nocsd does not reach nocs-system"
code=$(curl -s -o /dev/null -w '%{http_code}' "${api[@]}" -X POST http://127.0.0.1:8000/api/system/reboot)
[[ $code == 503 ]] || fail "a reboot from the app was not refused on a PC (HTTP $code)"
# Restarting indiserver from the app (ADR 0030): a new process, and nocsd back on it.
indiserver=$(systemctl show -p MainPID --value nocs-indiserver)
code=$(curl -s -o /dev/null -w '%{http_code}' "${api[@]}" -X POST \
    http://127.0.0.1:8000/api/system/services/indiserver/restart)
[[ $code == 204 ]] || fail "restarting indiserver from the app failed (HTTP $code)"
[[ $(systemctl show -p MainPID --value nocs-indiserver) != "$indiserver" ]] \
    || fail "indiserver was not restarted"
for _ in $(seq 60); do health 2>/dev/null | grep -q '"indi_connected":true' && break; sleep 1; done
health | grep -q '"indi_connected":true' || fail "nocsd did not reconnect to the restarted indiserver"
runuser -u nocs -- sh -c 'echo start indi_simulator_telescope > /run/indi/fifo'
for _ in $(seq 30); do pgrep -u nocs -f indi_simulator_telescope >/dev/null && break; sleep 1; done
pgrep -u nocs -f indi_simulator_telescope >/dev/null || fail "indiserver did not start a driver from the FIFO"
for _ in $(seq 60); do (echo > /dev/tcp/127.0.0.1/4400) 2>/dev/null && break; sleep 1; done
(echo > /dev/tcp/127.0.0.1/4400) 2>/dev/null || fail "PHD2 does not listen on 4400"
# An upgrade (here: the same version again) restarts nocsd and leaves indiserver alone.
before=$(systemctl show -p MainPID --value nocs-indiserver)
nocsd=$(systemctl show -p MainPID --value nocsd)
apt-get install -y --reinstall /debs/*.deb >/dev/null 2>&1
for _ in $(seq 60); do health 2>/dev/null | grep -q '"indi_connected":true' && break; sleep 1; done
health | grep -q '"indi_connected":true' || fail "nocsd did not come back after the upgrade"
[[ $(systemctl show -p MainPID --value nocsd) != "$nocsd" ]] || fail "the upgrade did not restart nocsd"
[[ $(systemctl show -p MainPID --value nocs-indiserver) == "$before" ]] || fail "the upgrade restarted indiserver"
echo "PASS"
CHECK
}
check

[[ -n $appliance ]] || exit 0
docker exec -i "$name" bash -s <<'CHECK'
set -euo pipefail
fail() { echo "FAIL: $*"; systemctl status --no-pager nocsd nocs-firewall || true; journalctl --no-pager -n 60 -u nocsd -u nocs-firewall; exit 1; }
DEBIAN_FRONTEND=noninteractive apt-get install -y /debs/appliance/*.deb >/dev/null 2>&1 \
    || fail "nocs-appliance does not install"
[[ $(systemctl is-active nocs-firewall) == active ]] || fail "the firewall is not up"
[[ $(nft list chain inet nocs input) == *'policy drop'* ]] || fail "no firewall rules"
[[ $(systemctl is-enabled systemd-networkd.service) == disabled ]] || fail "systemd-networkd is still enabled"
health() { curl -fsS -H 'Host: localhost' http://127.0.0.1/api/health; }
for _ in $(seq 60); do health 2>/dev/null | grep -q '"indi_connected":true' && break; sleep 1; done
health | grep -q '"indi_connected":true' || fail "nocsd does not answer on port 80"
runuser -u nocs -- /opt/nocs/venv/bin/nocs-system call hello | grep -q '"network.status"' \
    || fail "nocs-system does not offer the appliance's operations"
# The SMB share (ADR 0037): off, Samba's own services masked, nothing on 445.
listening() { (echo > /dev/tcp/127.0.0.1/445) 2>/dev/null; }
for unit in smbd nmbd; do
    [[ $(systemctl is-enabled "$unit" 2>/dev/null) == masked ]] || fail "$unit is not masked"
    [[ $(systemctl is-active "$unit") != active ]] || fail "$unit runs"
done
! listening || fail "something listens on 445 with the share off"
share() { local args=${2:-'{}'}; runuser -u nocs -- /opt/nocs/venv/bin/nocs-system call "share.$1" "$args"; }
share enable '{"on": true}' | grep -q '"on": true' || fail "the share does not switch on"
for _ in $(seq 30); do listening && break; sleep 1; done
[[ $(systemctl is-active nocs-share nocs-wsdd) == $'active\nactive' ]] \
    || { journalctl --no-pager -n 40 -u nocs-share -u nocs-wsdd; fail "smbd or wsdd is not running"; }
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends smbclient >/dev/null 2>&1
install -d -o nocs -g nocs /var/lib/nocs/NOCS/2026-11-01
echo frame > /var/lib/nocs/NOCS/2026-11-01/a.fits
smbclient -N -L //127.0.0.1 2>/dev/null | grep -q 'Internal *Disk' || fail "the share does not list Internal to a guest"
smbclient -N //127.0.0.1/Internal -c 'get 2026-11-01/a.fits /tmp/a.fits' >/dev/null 2>&1 \
    && [[ $(cat /tmp/a.fits) == frame ]] || fail "a guest cannot read a frame"
smbclient -U nocs%nocs //127.0.0.1/Internal -c ls 2>/dev/null | grep -q 2026-11-01 || fail "nocs / nocs cannot log in"
smbclient -U nocs%wrong //127.0.0.1/Internal -c ls >/dev/null 2>&1 && fail "a wrong password for nocs was let in"
put=$(smbclient -N //127.0.0.1/Internal -c 'put /tmp/a.fits b.fits' 2>&1 || true)
[[ ! -e /var/lib/nocs/NOCS/b.fits && $put == *NT_STATUS_* ]] || fail "the share is writable: $put"
smbclient -N //127.0.0.1/Internal -c 'ls ../config/*' 2>&1 | grep -q auth.json && fail "the data directory is shared"
share status | grep -q '"name": "Internal"' || fail "share.status does not list Internal"
share enable '{"on": false}' >/dev/null || fail "the share does not switch off"
! listening || fail "smbd still listens with the share off"
systemctl enable --now nocs-share >/dev/null 2>&1  # left on, for the removal below
DEBIAN_FRONTEND=noninteractive apt-get remove -y nocs-appliance >/dev/null 2>&1 || fail "nocs-appliance does not remove"
! nft list table inet nocs >/dev/null 2>&1 || fail "the firewall stayed after removing nocs-appliance"
! listening || fail "smbd still listens after removing nocs-appliance"
[[ $(systemctl is-enabled smbd 2>/dev/null) != masked ]] || fail "smbd stayed masked after removing nocs-appliance"
echo "PASS: appliance"
CHECK
