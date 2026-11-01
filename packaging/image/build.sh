#!/usr/bin/env bash
# Build the NOCS image for the Raspberry Pi 5 from Ubuntu's own (ADR 0026): the
# official preinstalled server image, changed in a chroot, checked by booting it in
# a container (smoke-test.sh), then compressed.
#
#   sudo packaging/image/build.sh packaging/out/nocs_<version>_arm64.deb
#
# Run it as root on arm64 (CI: ubuntu-24.04-arm). It needs losetup, sfdisk,
# e2fsprogs, xz, unzip, curl and, for the smoke test, systemd-nspawn.
#
# Environment (defaults in brackets):
#   OUT [packaging/out]  CACHE [~/.cache/nocs: Ubuntu's image and ASTAP]
#   UBUNTU_RELEASE [26.04]  GROW [3G: added to the root filesystem]  SMOKE_TEST [1]
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
DEB=$(realpath "${1:?usage: $0 <nocs .deb for arm64>}")
OUT=$(realpath "${OUT:-$REPO/packaging/out}")
CACHE=${CACHE:-$HOME/.cache/nocs}
RELEASE=${UBUNTU_RELEASE:-26.04}
GROW=${GROW:-3G}
BASE=https://cdimage.ubuntu.com/releases/$RELEASE/release
# The same files the lab setup installs (dev/pi/nocs-lab-setup.sh); ADR 0018.
ASTAP_CLI_URL=https://sourceforge.net/projects/astap-program/files/linux_installer/astap_command-line_version_Linux_aarch64.zip/download
ASTAP_DB_URL=https://sourceforge.net/projects/astap-program/files/star_databases/d50_star_database.deb/download

die() { echo "error: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

[[ $(id -u) == 0 ]] || die "run as root (it mounts the image)"
[[ $(uname -m) == aarch64 ]] || die "build on arm64: the chroot runs the image's own programs"
[[ $(dpkg-deb -f "$DEB" Architecture) == arm64 ]] || die "$DEB is not an arm64 package"
version=$(dpkg-deb -f "$DEB" Version)
name=nocs-${version//\~/-}-pi5-arm64
mkdir -p "$OUT" "$CACHE/astap"

# -- inputs: Ubuntu's image (checked against its SHA256SUMS) and ASTAP ----------------
step "Ubuntu $RELEASE for the Raspberry Pi"
sums=$(curl -fsSL "$BASE/SHA256SUMS") || die "cannot fetch $BASE/SHA256SUMS"
line=$(grep -E 'preinstalled-server-arm64\+raspi\.img\.xz$' <<<"$sums" | sort -V -k2 | tail -1)
[[ -n $line ]] || die "no Raspberry Pi server image listed for $RELEASE"
sha=${line%% *}
ubuntu=${line##*[ *]}
if ! { [[ -f $CACHE/$ubuntu ]] && echo "$sha  $CACHE/$ubuntu" | sha256sum -c --quiet 2>/dev/null; }; then
    curl -fL --progress-bar -o "$CACHE/$ubuntu.part" "$BASE/$ubuntu"
    echo "$sha  $CACHE/$ubuntu.part" | sha256sum -c --quiet || die "checksum mismatch for $ubuntu"
    mv "$CACHE/$ubuntu.part" "$CACHE/$ubuntu"
fi
echo "$ubuntu (SHA256 verified)"

# SourceForge serves a fresh connection fast and then throttles it hard: give up on a
# slow one and resume on a new connection.
fetch() {
    local file=$1 url=$2
    [[ -f $file ]] && return
    for _ in $(seq 60); do
        curl -fsSL -C - --speed-limit 1000000 --speed-time 20 -o "$file.part" "$url" && break
        sleep 2
    done
    mv "$file.part" "$file"
}
step "ASTAP and its D50 star database"
fetch "$CACHE/astap/astap_cli_aarch64.zip" "$ASTAP_CLI_URL"
fetch "$CACHE/astap/d50_star_database.deb" "$ASTAP_DB_URL"
dpkg-deb -f "$CACHE/astap/d50_star_database.deb" Package >/dev/null || die "the D50 download is not a package"

# -- the image, grown, its partitions on a loop device --------------------------------
work=$(mktemp -d "$OUT/.image.XXXXXX")
img=$work/$name.img
root=$work/root
loop=
cleanup() {
    set +e
    if [[ -n $loop ]]; then
        for point in run dev/pts dev sys proc boot/firmware ""; do
            mountpoint -q "$root/$point" && umount -R "$root/$point"
        done
        losetup -d "$loop"
    fi
    rm -rf "$work"
}
trap cleanup EXIT

step "Unpacking and growing the image by $GROW"
xz -dc "$CACHE/$ubuntu" > "$img"
truncate -s +"$GROW" "$img"
echo ", +" | sfdisk --quiet --no-reread -N 2 "$img"
loop=$(losetup --find --show --partscan "$img")
e2fsck -pf "${loop}p2" || (( $? <= 1 ))
resize2fs "${loop}p2"
mkdir -p "$root"
mount "${loop}p2" "$root"
mkdir -p "$root/boot/firmware"  # the image's fstab mounts it there at boot
mount "${loop}p1" "$root/boot/firmware"
for point in proc sys dev dev/pts; do
    mount --bind "/$point" "$root/$point"
done
# An empty /run: maintainer scripts must not find (and talk to) this machine's systemd.
mount -t tmpfs tmpfs "$root/run"
mkdir -p "$root/run/systemd/resolve"
cp -L /etc/resolv.conf "$root/run/systemd/resolve/stub-resolv.conf"
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod 755 "$root/usr/sbin/policy-rc.d"

in_image() { chroot "$root" /usr/bin/env DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 "$@"; }

# -- software ---------------------------------------------------------------------------
step "INDI, PHD2 and NOCS"
cp "$DEB" "$root/tmp/nocs.deb"
cp "$CACHE/astap/d50_star_database.deb" "$root/tmp/d50.deb"
in_image apt-get update
in_image apt-get install -y --no-install-recommends software-properties-common
in_image add-apt-repository -y --no-update ppa:mutlaqja/ppa
in_image add-apt-repository -y --no-update ppa:pch/phd2
in_image apt-get update
in_image apt-get install -y /tmp/nocs.deb indi-bin indi-3rdparty-drivers phd2 xvfb avahi-daemon \
    chrony gpsd network-manager dnsmasq-base iw nftables
in_image dpkg -i /tmp/d50.deb
mkdir -p "$root/opt/astap"
unzip -o -q "$CACHE/astap/astap_cli_aarch64.zip" -d "$root/opt/astap"
chmod 755 "$root/opt/astap/astap_cli"
[[ -n $(compgen -G "$root/opt/astap/d50_*") ]] || die "D50 did not install into /opt/astap"

step "Removing snapd"
in_image apt-get purge -y snapd
in_image apt-get autoremove -y --purge
rm -rf "$root/snap" "$root/var/snap" "$root/var/lib/snapd" "$root/var/cache/snapd"

# -- configuration ----------------------------------------------------------------------
step "Configuration"
# Nothing installs or restarts behind a session (ADR 0025).
cat > "$root/etc/apt/apt.conf.d/52nocs-unattended-upgrades" <<'EOF'
// NOCS (ADR 0025): download updates, and install them only when the owner asks.
APT::Periodic::Unattended-Upgrade "0";
APT::Periodic::Download-Upgradeable-Packages "1";
EOF
mkdir -p "$root/etc/needrestart/conf.d"
cat > "$root/etc/needrestart/conf.d/nocs.conf" <<'EOF'
# NOCS (ADR 0025): list the services an upgrade affects, restart none of them.
$nrconf{restart} = 'l';
EOF
# A USB GPS gives chrony the time (and nocsd the site) through gpsd (ADR 0029).
cat > "$root/etc/default/gpsd" <<'EOF'
# NOCS (ADR 0029): find USB GPS receivers when they are plugged in, and read them
# without waiting for a client, so that chrony always gets their time.
DEVICES=""
USBAUTO="true"
GPSD_OPTIONS="-n"
EOF
grep -q '^confdir /etc/chrony/conf.d' "$root/etc/chrony/chrony.conf" ||
    sed -i '1i confdir /etc/chrony/conf.d' "$root/etc/chrony/chrony.conf"
mkdir -p "$root/etc/chrony/conf.d"
cat > "$root/etc/chrony/conf.d/nocs-gps.conf" <<'EOF'
# NOCS (ADR 0029): a USB GPS's time, from gpsd's shared memory. Without a PPS signal
# it is good to tens of milliseconds: plenty for pointing and FITS headers.
refclock SHM 0 refid GPS precision 1e-1 offset 0.1 delay 0.2
EOF
# The box is the appliance: nocs-system does everything nocsd may ask (ADR 0027).
mkdir -p "$root/etc/nocs/system.conf.d"
cat > "$root/etc/nocs/system.conf.d/appliance.conf" <<'EOF'
# NOCS appliance (ADR 0027): restart, shut down, rename, mount and eject USB drives,
# set the clock from a client when nothing else keeps it, restart indiserver/PHD2,
# and run the Wi-Fi: access point, station and the fallback (ADR 0028).
[operations]
enabled = power hostname storage time services network
EOF
# A hung kernel reboots the Pi (its hardware watchdog, ADR 0030).
mkdir -p "$root/etc/systemd/system.conf.d"
cat > "$root/etc/systemd/system.conf.d/nocs-watchdog.conf" <<'EOF'
[Manager]
RuntimeWatchdogSec=30s
EOF
# NetworkManager runs the network, so that the box can be an access point; netplan
# (and the Wi-Fi that Raspberry Pi Imager presets through cloud-init) hand it over
# (ADR 0028).
cat > "$root/etc/netplan/01-nocs-network-manager.yaml" <<'EOF'
# NOCS (ADR 0028): NetworkManager runs the network.
network:
  version: 2
  renderer: NetworkManager
EOF
chmod 600 "$root/etc/netplan/01-nocs-network-manager.yaml"
in_image systemctl disable systemd-networkd.service systemd-networkd.socket \
    systemd-networkd-wait-online.service
mkdir -p "$root/etc/NetworkManager/conf.d"
cat > "$root/etc/NetworkManager/conf.d/nocs.conf" <<'EOF'
# NOCS (ADR 0028): Wi-Fi power saving makes the Pi miss frames from phones.
[connection]
wifi.powersave=2
EOF
# Only what clients need reaches the box; indiserver (7624) and PHD2's event server
# (4400), which have no authentication, only from the box itself (ADR 0028).
cat > "$root/etc/nftables.conf" <<'EOF'
#!/usr/sbin/nft -f
# NOCS (ADR 0028): what the network may reach on the box. NetworkManager adds its
# own tables for the access point; this one only filters what comes in.
table inet nocs
delete table inet nocs
table inet nocs {
    chain input {
        type filter hook input priority filter; policy drop;
        iif lo accept
        ct state established,related accept
        ct state invalid drop
        meta l4proto { icmp, ipv6-icmp } accept
        tcp dport { 22, 80 } accept
        udp dport 5353 accept
        udp dport { 67, 68 } accept
        meta l4proto { tcp, udp } th dport 53 accept
    }
}
EOF
in_image systemctl enable nftables.service
# nocsd on port 80: http://nocs.local, without a port (ADR 0028).
mkdir -p "$root/etc/systemd/system/nocsd.service.d"
cat > "$root/etc/systemd/system/nocsd.service.d/appliance.conf" <<'EOF'
[Service]
Environment=NOCS_PORT=80
AmbientCapabilities=CAP_NET_BIND_SERVICE
EOF
# Browsers and apps that browse for web servers find the box over mDNS (ADR 0028).
mkdir -p "$root/etc/avahi/services"
cat > "$root/etc/avahi/services/nocs.service" <<'EOF'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">NOCS on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>80</port>
  </service>
</service-group>
EOF
# SSH only with a key (from Raspberry Pi Imager's presets): never a password.
cat > "$root/etc/ssh/sshd_config.d/50-nocs.conf" <<'EOF'
# NOCS (ADR 0028): keys only.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
echo nocs > "$root/etc/hostname"
sed -i '/^127\.0\.1\.1/d' "$root/etc/hosts"
sed -i '/^127\.0\.0\.1/a 127.0.1.1\tnocs' "$root/etc/hosts"
# No login user and no password (ADR 0026). Raspberry Pi Imager writes its own
# user-data instead of this one when the image is customised (Wi-Fi, SSH key).
cat > "$root/boot/firmware/user-data" <<'EOF'
#cloud-config
# NOCS: no login user and no password. Raspberry Pi Imager replaces this file with
# its own when you customise the image (Wi-Fi, host name, SSH key).
hostname: nocs
users: []
disable_root: true
ssh_pwauth: false
EOF
# Every Pi makes its own identity at first boot.
: > "$root/etc/machine-id"
rm -f "$root/var/lib/dbus/machine-id" "$root"/etc/ssh/ssh_host_*

in_image dpkg-query -W -f '${Package} ${Version}\n' > "$OUT/$name.manifest.txt"
in_image apt-get clean
rm -rf "$root"/var/lib/apt/lists/* "$root/tmp/nocs.deb" "$root/tmp/d50.deb"
rm -f "$root/usr/sbin/policy-rc.d"
df -h "$root" "$root/boot/firmware"

# -- check, shrink the free space, compress ---------------------------------------------
for point in run dev/pts dev sys proc; do
    umount "$root/$point"
done
if [[ ${SMOKE_TEST:-1} == 1 ]]; then
    step "Smoke test"
    "$HERE/smoke-test.sh" "$root"
fi
fstrim "$root" || true
umount "$root/boot/firmware" "$root"
e2fsck -pf "${loop}p2" || (( $? <= 1 ))
losetup -d "$loop"
loop=

step "Compressing"
xz -T0 -6 -c "$img" > "$OUT/$name.img.xz"
(cd "$OUT" && sha256sum "$name.img.xz" > "$name.img.xz.sha256")
ls -l "$OUT/$name".*
