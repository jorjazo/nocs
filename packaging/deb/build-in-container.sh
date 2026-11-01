#!/bin/bash
# Runs inside packaging/deb/Containerfile (see build.sh): builds nocs_<version>_<arch>.deb
# from the repository mounted read-only at /src, with the web app built in
# $WEB_DIST, into /out.
set -euo pipefail

: "${VERSION:?}" "${WEB_DIST:?}"
arch=$(dpkg --print-architecture)
python=3.13  # sep has no arm64 wheels for 3.14 (docs/spikes/pi5-performance.md)
stage=$(mktemp -d)
build=$(mktemp -d)

# The environment is created at its final path so its scripts and pyvenv.cfg need
# no rewriting (ADR 0025).
export UV_PYTHON_INSTALL_DIR=/opt/nocs/python UV_PROJECT_ENVIRONMENT=/opt/nocs/venv
export UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_PREFERENCE=only-managed
rm -rf /opt/nocs
uv python install --no-bin "$python"
uv venv --python "$python" /opt/nocs/venv
# A copy, so building the nocs wheel cannot write into the read-only checkout.
cp -a /src/server/pyproject.toml /src/server/uv.lock /src/server/src "$build/"
uv sync --project "$build" --locked --no-dev --no-editable --no-python-downloads
rm -rf /opt/nocs/python/.lock /opt/nocs/python/.temp /opt/nocs/python/.cache
/opt/nocs/venv/bin/python -c 'import cv2, sep, astropy, nocs.api'

mkdir -p "$stage/opt" "$stage/DEBIAN"
cp -a /opt/nocs "$stage/opt/"
cp -a "$WEB_DIST" "$stage/opt/nocs/web"
install -D -m 755 /src/dev/phd2/entrypoint.sh "$stage/opt/nocs/libexec/nocs-phd2"
(cd /src/packaging/deb/root && find . -type f) | while read -r file; do
    install -D -m 644 "/src/packaging/deb/root/$file" "$stage/$file"
done
# The apt repository's public key (ADR 0035), once it has one.
keyring=/src/packaging/repo/nocs-archive-keyring.asc
if [[ -f $keyring ]]; then
    install -D -m 644 "$keyring" "$stage/usr/share/keyrings/nocs-archive-keyring.asc"
fi

size=$(du -sk "$stage" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$arch/" -e "s/@SIZE@/$size/" \
    /src/packaging/deb/debian/control > "$stage/DEBIAN/control"
install -m 644 /src/packaging/deb/debian/conffiles "$stage/DEBIAN/"
for script in postinst prerm postrm; do
    install -m 755 "/src/packaging/deb/debian/$script" "$stage/DEBIAN/"
done
deb="/out/nocs_${VERSION}_${arch}.deb"
dpkg-deb --root-owner-group --build "$stage" "$deb"
if [[ -n ${HOST_UID:-} ]]; then chown "$HOST_UID:${HOST_GID:-$HOST_UID}" "$deb"; fi
