#!/usr/bin/env bash
# Boot an image's root filesystem in a container and check that NOCS comes up
# (ADR 0026): its services run, nocsd answers and is connected to indiserver,
# indiserver starts a driver through the FIFO, PHD2 listens, ASTAP has D50, and
# chrony reads a GPS through gpsd (ADR 0029).
#
#   sudo packaging/image/smoke-test.sh <mounted root filesystem>
#
# Changes stay in a temporary overlay (--volatile=overlay): the image is left as it
# was, with no machine id of its own. Needs systemd-nspawn (systemd-container).
set -euo pipefail

root=$(realpath "${1:?usage: $0 <root filesystem>}")
machine=nocs-smoke-$$
fstab=$(mktemp)
console=$(mktemp)
trap 'machinectl terminate "$machine" >/dev/null 2>&1 || true; rm -f "$fstab" "$console"' EXIT

# A container has no SD card to mount, and cloud-init has nothing to configure.
: > "$fstab"
systemd-nspawn --quiet --boot --volatile=overlay --private-network \
    --machine="$machine" --directory="$root" --bind-ro="$fstab:/etc/fstab" -- \
    systemd.mask=cloud-init-local.service systemd.mask=cloud-init-network.service \
    systemd.mask=cloud-init.service systemd.mask=cloud-config.service \
    systemd.mask=cloud-final.service >"$console" 2>&1 &
nspawn=$!

run() { systemd-run --machine="$machine" --wait --pipe --quiet "$@"; }
for _ in $(seq 120); do
    run /bin/true 2>/dev/null && break
    sleep 1
done
run /bin/true || { echo "FAIL: the container did not boot"; tail -50 "$console"; exit 1; }

status=0
run /bin/bash -s <<'CHECK' || status=$?
set -euo pipefail
fail() {
    echo "FAIL: $*"
    systemctl --no-pager --failed || true
    journalctl --no-pager -n 80 -u nocsd -u nocs-indiserver -u nocs-phd2 -u nocs-system || true
    exit 1
}
health() { curl -fsS -H 'Host: localhost' http://127.0.0.1/api/health; }
for _ in $(seq 120); do health 2>/dev/null | grep -q '"indi_connected":true' && break; sleep 1; done
health | grep -q '"indi_connected":true' || fail "nocsd does not answer, or is not connected to indiserver"
echo "health: $(health)"
for unit in nocsd nocs-indiserver nocs-system avahi-daemon; do
    [[ $(systemctl is-active "$unit") == active ]] || fail "$unit is not active"
done
runuser -u nocs -- sh -c 'echo start indi_simulator_telescope > /run/indi/fifo'
for _ in $(seq 30); do pgrep -u nocs -f indi_simulator_telescope >/dev/null && break; sleep 1; done
pgrep -u nocs -f indi_simulator_telescope >/dev/null || fail "indiserver did not start a driver"
for _ in $(seq 60); do (echo > /dev/tcp/127.0.0.1/4400) 2>/dev/null && break; sleep 1; done
(echo > /dev/tcp/127.0.0.1/4400) 2>/dev/null || fail "PHD2 does not listen on 4400"
[[ -x /opt/astap/astap_cli ]] || fail "no ASTAP"
[[ $(find /opt/astap -name 'd50_*' | wc -l) -gt 100 ]] || fail "no D50 database"
[[ $(hostname) == nocs ]] || fail "the host name is $(hostname), not nocs"
chronyd -p 2>/dev/null | grep -q '^refclock SHM 0' || fail "chrony does not read the GPS"
[[ $(systemctl is-enabled gpsd.socket) == enabled ]] || fail "gpsd is not enabled"
for unit in NetworkManager nftables; do
    [[ $(systemctl is-active "$unit") == active ]] || fail "$unit is not active"
done
[[ $(systemctl is-enabled systemd-networkd.service) == disabled ]] || fail "systemd-networkd still runs"
nft list chain inet nocs input | grep -q 'policy drop' || fail "no firewall"
runuser -u nocs -- /opt/nocs/venv/bin/nocs-system call network.status | grep -q '"ap_ssid": "NOCS-' \
    || fail "nocs-system does not manage the network"
runuser -u nocs -- /opt/nocs/venv/bin/nocs-system call hello | grep -q '"time.set"' \
    || fail "nocs-system does not offer the appliance's operations"
[[ ! -e /snap ]] && ! command -v snap >/dev/null || fail "snapd is still there"
echo PASS
CHECK

machinectl poweroff "$machine" >/dev/null 2>&1 || true
wait "$nspawn" || true
exit "$status"
