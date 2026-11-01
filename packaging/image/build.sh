#!/usr/bin/env bash
# Build the NOCS image for the Raspberry Pi 5 from Ubuntu's own (ADR 0026): the
# official preinstalled server image, changed in a chroot, checked by booting it in
# a container (smoke-test.sh), then compressed.
#
#   sudo packaging/image/build.sh packaging/out/nocs_<version>_arm64.deb
#
# nocs-appliance_<version>_all.deb is taken from the same directory.
# Run it as root on arm64 (CI: ubuntu-24.04-arm). It needs losetup, sfdisk,
# e2fsprogs, xz, unzip, curl and, for the smoke test, systemd-nspawn.
#
# Environment (defaults in brackets):
#   OUT [packaging/out]  CACHE [~/.cache/nocs: Ubuntu's image and ASTAP]
#   UBUNTU_RELEASE [26.04]  GROW [3G: added to the root filesystem]  SMOKE_TEST [1]
#   NOCS_APT_URL [none: no NOCS repository]  NOCS_APT_SUITE [testing]: the repository
#   the box updates from (ADR 0035)
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
APPLIANCE=$(dirname "$DEB")/nocs-appliance_${version}_all.deb
[[ -f $APPLIANCE ]] || die "no $APPLIANCE next to $DEB (packaging/deb/build.sh makes both)"
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
cp "$APPLIANCE" "$root/tmp/nocs-appliance.deb"
cp "$CACHE/astap/d50_star_database.deb" "$root/tmp/d50.deb"
in_image apt-get update
in_image apt-get install -y --no-install-recommends software-properties-common
in_image add-apt-repository -y --no-update ppa:mutlaqja/ppa
in_image add-apt-repository -y --no-update ppa:pch/phd2
in_image apt-get update
# nocs-appliance makes the box the appliance: the network, the firewall, port 80,
# updates only downloaded, the GPS, the hardware watchdog (ADR 0025, 0028, 0029, 0030).
in_image apt-get install -y /tmp/nocs.deb /tmp/nocs-appliance.deb indi-bin indi-3rdparty-drivers \
    phd2 xvfb
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
# Everything else that makes the box the appliance comes from nocs-appliance, so
# that updates reach it; only the first boot's identity is the image's own.
# The box updates NOCS from its own repository (ADR 0035), once there is one.
if [[ -n ${NOCS_APT_URL:-} && -f $root/usr/share/keyrings/nocs-archive-keyring.asc ]]; then
    cat > "$root/etc/apt/sources.list.d/nocs.sources" <<EOF
Types: deb
URIs: $NOCS_APT_URL
Suites: ${NOCS_APT_SUITE:-testing}
Components: main
Signed-By: /usr/share/keyrings/nocs-archive-keyring.asc
EOF
fi
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
rm -rf "$root"/var/lib/apt/lists/* "$root"/tmp/nocs*.deb "$root/tmp/d50.deb"
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
