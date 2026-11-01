#!/usr/bin/env bash
# Build nocs-appliance_<version>_all.deb, which makes a box the NOCS appliance
# (ADR 0025). Only configuration: dpkg-deb on any machine builds it.
#
#   packaging/appliance/build.sh <version> [out dir: packaging/out]
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
version=${1:?usage: $0 <version> [out dir]}
out=$(realpath "${2:-$here/../out}")
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

cp -a "$here/root/." "$stage/"
find "$stage" -type d -exec chmod 755 {} +
find "$stage" -type f -exec chmod 644 {} +
# netplan refuses to read a file others can read.
chmod 600 "$stage/usr/lib/netplan/"*.yaml
mkdir -p "$stage/DEBIAN"
size=$(du -sk "$stage" | cut -f1)
sed -e "s/@VERSION@/$version/" -e "s/@SIZE@/$size/" "$here/debian/control" > "$stage/DEBIAN/control"
install -m 644 "$here/debian/conffiles" "$stage/DEBIAN/"
for script in postinst prerm postrm; do
    install -m 755 "$here/debian/$script" "$stage/DEBIAN/"
done
mkdir -p "$out"
dpkg-deb --root-owner-group --build "$stage" "$out/nocs-appliance_${version}_all.deb"
