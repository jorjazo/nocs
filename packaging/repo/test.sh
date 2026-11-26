#!/usr/bin/env bash
# Check publish.py against a local directory: publish small throwaway packages to
# testing and stable with a throwaway key, then let apt on Ubuntu 26.04 trust,
# list and install them; older versions beyond what a suite keeps leave the pool.
# Throwaway images too, and Raspberry Pi Imager's list of them.
#
#   packaging/repo/test.sh
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

export GNUPGHOME=$work/gnupg
mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --passphrase '' --quick-generate-key "NOCS test <test@invalid>" ed25519 sign 1d
APT_SIGNING_KEY=$(gpg --batch --armor --export-secret-keys)
export APT_SIGNING_KEY
gpg --batch --armor --export > "$work/keyring.asc"

package() {  # name version arch
    local stage=$work/stage-$1-$2-$3
    mkdir -p "$stage/DEBIAN" "$stage/usr/share/$1"
    echo "$2" > "$stage/usr/share/$1/version"
    printf 'Package: %s\nVersion: %s\nArchitecture: %s\nMaintainer: test <test@invalid>\nDescription: test\n multi-line\n' \
        "$1" "$2" "$3" > "$stage/DEBIAN/control"
    dpkg-deb --root-owner-group --build "$stage" "$work/$1_$2_$3.deb" >/dev/null
    echo "$work/$1_$2_$3.deb"
}

repo=$work/repo
mkdir "$repo"
publish() { python3 "$here/publish.py" --local "$repo" "$@" >/dev/null; }
for version in 0.1.0~git1.ga 0.1.0~git2.gb 0.1.0~git3.gc; do
    publish debs --suite testing:2 "$(package nocs "$version" amd64)" "$(package nocs "$version" arm64)" \
        "$(package nocs-appliance "$version" all)"
done
publish debs --suite stable:3 --suite testing:2 "$(package nocs 0.1.0 amd64)" \
    "$(package nocs 0.1.0 arm64)" "$(package nocs-appliance 0.1.0 all)"

# After its release, main's builds sort after it (ADR 0045): testing moves on to them.
for version in 0.1.0.git4.gd 0.1.0.git5.ge; do
    publish debs --suite testing:2 "$(package nocs "$version" amd64)" "$(package nocs "$version" arm64)" \
        "$(package nocs-appliance "$version" all)"
done

pool=$(cd "$repo" && find pool -name '*.deb' | sort)
echo "$pool"
[[ $(grep -c . <<<"$pool") == 9 ]] || fail "the pool should hold three versions of three packages"
grep -q 'nocs_0.1.0.git5.ge_amd64.deb' <<<"$pool" || fail "testing lost its newest build"
grep -q 'nocs_0.1.0_amd64.deb' <<<"$pool" || fail "stable lost its release"
! grep -q 'git[1-3]\.' <<<"$pool" || fail "old testing builds were not pruned"

# Images: the newest two stay, an rc sorts before its release; Imager's list names
# them, newest first, with the sizes and checksums of the image and of its contents.
for version in 0.1.0-rc1 0.1.0 0.0.9; do
    image=$work/nocs-$version-pi5-arm64.img.xz
    echo "$version" | xz > "$image"
    sha256sum "$image" > "$image.sha256"
    publish image --keep 2 --url https://apt.example/ "$image" "$image.sha256"
done
images=$(cd "$repo/images" && ls nocs-*-pi5-arm64.*)
[[ $images == $'nocs-0.1.0-pi5-arm64.imager.json\nnocs-0.1.0-pi5-arm64.img.xz\nnocs-0.1.0-pi5-arm64.img.xz.sha256\nnocs-0.1.0-rc1-pi5-arm64.imager.json\nnocs-0.1.0-rc1-pi5-arm64.img.xz\nnocs-0.1.0-rc1-pi5-arm64.img.xz.sha256' ]] \
    || fail "images kept: $images"
[[ -f $repo/images/nocs-icon.svg ]] || fail "no icon for Imager"
python3 - "$repo/images/rpi-imager.json" "$(echo 0.1.0 | sha256sum | cut -d' ' -f1)" <<'IMAGER' \
    || fail "Imager's list: $(cat "$repo/images/rpi-imager.json")"
import json, sys
listing = json.load(open(sys.argv[1]))
assert listing["imager"]["devices"][0]["tags"] == ["pi5-64bit"]
first, second = listing["os_list"]
assert [first["name"], second["name"]] == ["NOCS 0.1.0", "NOCS 0.1.0rc1"]
assert first["url"] == "https://apt.example/images/nocs-0.1.0-pi5-arm64.img.xz"
assert first["icon"] == "https://apt.example/images/nocs-icon.svg"
assert first["init_format"] == "cloudinit" and first["devices"] == ["pi5-64bit"]
assert first["extract_size"] == len("0.1.0\n") and first["extract_sha256"] == sys.argv[2]
IMAGER

docker run --rm -i -v "$repo:/repo:ro" -v "$work/keyring.asc:/usr/share/keyrings/nocs-test.asc:ro" \
    ubuntu:26.04 bash -s <<'CHECK' || fail "apt does not accept the repository"
set -euo pipefail
for suite in stable testing; do
    printf 'Types: deb\nURIs: file:/repo\nSuites: %s\nComponents: main\nSigned-By: /usr/share/keyrings/nocs-test.asc\n' \
        "$suite" > /etc/apt/sources.list.d/nocs.sources
    apt-get update -o Dir::Etc::sourcelist=/dev/null >/tmp/update 2>&1 || { cat /tmp/update; exit 1; }
    ! grep -q '^[WE]:' /tmp/update || { cat /tmp/update; exit 1; }
    apt-cache madison nocs nocs-appliance
done
# testing (the last source written) installs main's newest build, not the release.
apt-get install -y nocs nocs-appliance >/dev/null 2>&1
[[ $(dpkg-query -W -f '${Version}' nocs) == 0.1.0.git5.ge ]]
CHECK
echo PASS
