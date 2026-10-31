#!/usr/bin/env bash
# Installs the ASTAP command-line solver and a star database for development and CI.
#
#   dev/astap/install.sh [directory]        default: dev/.astap
#
# Then: NOCS_ASTAP=dev/.astap/astap_cli NOCS_ASTAP_DB=dev/.astap
#
# D05 (~100 MB) solves fields from 0.6° to 6°, which covers the simulators as the
# tests configure them and the reference rig. The appliance uses D50 (~900 MB, from
# 0.2°). SourceForge throttles long downloads, so CI caches the directory.
set -euo pipefail

DIR=${1:-$(dirname "$0")/../.astap}
DATABASE=${ASTAP_DATABASE:-d05}
case $(uname -m) in
    x86_64) ARCH=amd64 ;;
    aarch64) ARCH=aarch64 ;;
    *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
BASE=https://sourceforge.net/projects/astap-program/files
CLI_URL=$BASE/linux_installer/astap_command-line_version_Linux_$ARCH.zip/download
DB_URL=$BASE/star_databases/${DATABASE}_star_database.zip/download

download() { curl -fsSL --retry 3 -C - -o "$1" "$2"; }

mkdir -p "$DIR"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

if [[ ! -x $DIR/astap_cli ]]; then
    download "$tmp/cli.zip" "$CLI_URL"
    unzip -o -q "$tmp/cli.zip" -d "$DIR"
    chmod +x "$DIR/astap_cli"
fi
if ! compgen -G "$DIR/${DATABASE}_*.1476" >/dev/null; then
    download "$tmp/db.zip" "$DB_URL"
    unzip -o -q "$tmp/db.zip" -d "$DIR"
fi
"$DIR/astap_cli" -h | head -1
