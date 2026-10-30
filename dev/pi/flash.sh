#!/usr/bin/env bash
# Write Ubuntu Server for Raspberry Pi to an SD card, set up as a NOCS lab Pi on
# first boot (user + SSH key, Wi-Fi, Docker, uv, the repo and ASTAP).
#
#   dev/pi/flash.sh                 list candidate devices
#   dev/pi/flash.sh /dev/mmcblk0    write the card (asks for confirmation)
#   DRY_RUN=1 dev/pi/flash.sh       download and render the setup, write nothing
#
# Environment (defaults in brackets):
#   PI_USER [$USER]  PI_HOSTNAME [nocs-lab]  PI_TIMEZONE [this machine's]
#   SSH_KEY_FILE [~/.ssh/id_ed25519.pub]  WIFI_SSID / WIFI_PASSWORD [asked]
#   WIFI_COUNTRY [CL]  WITH_ASTAP [1]  UBUNTU_RELEASE [26.04]  FORCE [0]
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
DEVICE=${1:-}
RELEASE=${UBUNTU_RELEASE:-26.04}
BASE=https://cdimage.ubuntu.com/releases/$RELEASE/release
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/nocs
SSH_KEY_FILE=${SSH_KEY_FILE:-$HOME/.ssh/id_ed25519.pub}
export PI_USER=${PI_USER:-$USER}
export PI_HOSTNAME=${PI_HOSTNAME:-nocs-lab}
export PI_TIMEZONE=${PI_TIMEZONE:-$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)}
export WIFI_COUNTRY=${WIFI_COUNTRY:-CL}
export WITH_ASTAP=${WITH_ASTAP:-1}

die() { echo "error: $*" >&2; exit 1; }

# Some USB card readers (e.g. Realtek RTS5129) drop the card when USB autosuspend
# kicks in. Keep the reader awake until it is unplugged or the machine reboots.
keep_reader_awake() {
    local path
    path=$(readlink -f "/sys/class/block/$(basename "$1")/device" 2>/dev/null) || return 0
    while [[ $path == /sys/* ]]; do
        if [[ -f $path/idVendor && -f $path/power/control ]]; then
            [[ $(cat "$path/power/control") == on ]] || echo on | sudo tee "$path/power/control" >/dev/null
            return 0
        fi
        path=$(dirname "$path")
    done
}

candidates() {
    echo "Removable disks and SD cards:"
    lsblk -dpo NAME,TRAN,RM,SIZE,MODEL | awk 'NR==1 || $3==1 || $1 ~ /mmcblk/'
}

if [[ -z $DEVICE && ${DRY_RUN:-0} != 1 ]]; then
    candidates
    echo
    echo "usage: $0 <device>   (insert the card first; see the header of this script)"
    exit 1
fi

# -- safety checks on the target device ----------------------------------------
if [[ -n $DEVICE ]]; then
    [[ -b $DEVICE ]] || die "$DEVICE is not a block device"
    [[ $(lsblk -dno TYPE "$DEVICE") == disk ]] || die "$DEVICE is not a whole disk (give e.g. /dev/mmcblk0, not a partition)"
    if lsblk -nro MOUNTPOINTS "$DEVICE" | grep -qxE '/|/boot|/boot/efi|/home|/usr|/var|\[SWAP\]'; then
        die "$DEVICE holds a system mount point: refusing"
    fi
    removable=$(lsblk -dno RM "$DEVICE" | tr -d ' ')
    size_gb=$(( $(lsblk -dnbo SIZE "$DEVICE") / 1000000000 ))
    if [[ ${FORCE:-0} != 1 ]]; then
        [[ $removable == 1 || $DEVICE == /dev/mmcblk* ]] || die "$DEVICE is not removable (FORCE=1 to override)"
        (( size_gb <= 256 )) || die "$DEVICE is ${size_gb} GB, larger than any SD card expected (FORCE=1 to override)"
    fi
fi

# -- image: newest point release, verified against Ubuntu's SHA256SUMS ----------
mkdir -p "$CACHE"
sums=$(curl -fsSL "$BASE/SHA256SUMS") || die "cannot fetch $BASE/SHA256SUMS"
line=$(grep -E 'preinstalled-server-arm64\+raspi\.img\.xz$' <<<"$sums" | sort -V -k2 | tail -1)
[[ -n $line ]] || die "no Raspberry Pi server image listed for $RELEASE"
sha=${line%% *}
image=${line##*[ *]}
if ! { [[ -f $CACHE/$image ]] && echo "$sha  $CACHE/$image" | sha256sum -c --quiet 2>/dev/null; }; then
    echo "Downloading $image"
    curl -fL --progress-bar -o "$CACHE/$image.part" "$BASE/$image"
    echo "$sha  $CACHE/$image.part" | sha256sum -c --quiet || die "checksum mismatch for $image"
    mv "$CACHE/$image.part" "$CACHE/$image"
fi
echo "Image: $CACHE/$image (SHA256 verified)"

# -- first-boot configuration -----------------------------------------------------
[[ -f $SSH_KEY_FILE ]] || die "SSH public key not found: $SSH_KEY_FILE"
PI_SSH_KEY=$(head -1 "$SSH_KEY_FILE")
export PI_SSH_KEY
if [[ -z ${WIFI_SSID+set} ]]; then
    read -rp "Wi-Fi network name (empty for Ethernet only): " WIFI_SSID
fi
export WIFI_SSID
if [[ -n $WIFI_SSID && -z ${WIFI_PASSWORD:-} ]]; then
    read -rsp "Wi-Fi password for '$WIFI_SSID': " WIFI_PASSWORD
    echo
fi
export WIFI_PASSWORD=${WIFI_PASSWORD:-}

seed=$(mktemp -d)
trap 'rm -rf "$seed"' EXIT
python3 "$HERE/render_seed.py" "$seed"

echo
echo "Pi: $PI_HOSTNAME.local, user $PI_USER (key $(basename "$SSH_KEY_FILE")), timezone $PI_TIMEZONE"
echo "Network: ${WIFI_SSID:+Wi-Fi '$WIFI_SSID' ($WIFI_COUNTRY) and }Ethernet; ASTAP: $([[ $WITH_ASTAP == 1 ]] && echo yes || echo no)"

if [[ ${DRY_RUN:-0} == 1 ]]; then
    echo
    echo "DRY_RUN: nothing written. Rendered seed:"
    for f in user-data network-config meta-data; do
        echo "--- $f"
        sed -E 's/(password: ).*/\1"<redacted>"/' "$seed/$f"
    done
    exit 0
fi

# -- write ---------------------------------------------------------------------------
echo
lsblk -po NAME,SIZE,MODEL,MOUNTPOINTS "$DEVICE"
echo
echo "ALL DATA ON $DEVICE WILL BE ERASED."
read -rp "Type the device path to continue: " answer
[[ $answer == "$DEVICE" ]] || die "confirmation did not match; nothing written"

keep_reader_awake "$DEVICE"
for part in $(lsblk -nrpo NAME "$DEVICE" | tail -n +2); do
    sudo umount "$part" 2>/dev/null || true
done
# Direct I/O: without it the whole image (~4 GB) piles up as dirty page cache in
# front of a slow card, which can stall or freeze the desktop.
xz -dc "$CACHE/$image" |
    sudo dd of="$DEVICE" bs=4M iflag=fullblock oflag=direct conv=fsync status=progress
sudo partprobe "$DEVICE" 2>/dev/null || sudo blockdev --rereadpt "$DEVICE"
sudo udevadm settle

boot=$(lsblk -nrpo NAME,LABEL "$DEVICE" | awk '$2 == "system-boot" {print $1}')
[[ -n $boot ]] || die "boot partition (label system-boot) not found on $DEVICE"
mnt=$(mktemp -d)
sudo mount "$boot" "$mnt"
[[ -f $mnt/config.txt ]] || { sudo umount "$mnt"; die "boot partition looks incomplete: write the card again"; }
sudo cp "$seed/user-data" "$seed/network-config" "$seed/meta-data" "$mnt/"
sync
sudo umount "$mnt"
rmdir "$mnt"

cat <<EOF

Done. Put the card in the Pi and power it on. First boot installs everything
(about 10–20 minutes once it has internet; it retries until it does). Then:

    ssh $PI_USER@$PI_HOSTNAME.local
    cat /var/lib/nocs-lab/ready       # timestamp written when setup finished
    journalctl -u nocs-lab-setup      # setup progress (retries until online)

Note: the Wi-Fi password is stored in plain text on the card's boot partition
(as Ubuntu's own setup does).
EOF
