#!/usr/bin/env bash
# Build the nocs .deb for this machine's architecture (ADR 0025).
#
#   packaging/deb/build.sh            builds the web app, then the package, into packaging/out
#
# Environment (defaults in brackets):
#   OUT [packaging/out]  VERSION [from server/pyproject.toml and git]
#   WEB_DIST [build web/ with pnpm]  PLATFORM [this machine's, e.g. linux/arm64]
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
out=${OUT:-$repo/packaging/out}
mkdir -p "$out"

# Between releases: <pyproject version>~git<commits>.g<commit>, which sorts before
# the release itself. A tagged release (v<version>) is just <version>.
if [[ -z ${VERSION:-} ]]; then
    base=$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/server/pyproject.toml" | head -1)
    if git -C "$repo" describe --exact-match --tags --match "v$base" >/dev/null 2>&1; then
        VERSION=$base
    else
        VERSION="$base~git$(git -C "$repo" rev-list --count HEAD).g$(git -C "$repo" rev-parse --short=7 HEAD)"
    fi
fi

if [[ -z ${WEB_DIST:-} ]]; then
    pnpm --dir "$repo/web" install --frozen-lockfile
    pnpm --dir "$repo/web" build
    WEB_DIST=$repo/web/dist
fi
web=$(realpath "$WEB_DIST")
[[ -f $web/index.html ]] || { echo "error: no web app in $web" >&2; exit 1; }

platform=()
[[ -n ${PLATFORM:-} ]] && platform=(--platform "$PLATFORM")
docker build "${platform[@]}" -t nocs-deb-builder -f "$repo/packaging/deb/Containerfile" "$repo/packaging/deb"
docker run --rm "${platform[@]}" \
    -v "$repo:/src:ro" -v "$web:/web:ro" -v "$(realpath "$out"):/out" \
    -v nocs-deb-uv-cache:/root/.cache/uv \
    -e VERSION="$VERSION" -e WEB_DIST=/web -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    nocs-deb-builder /src/packaging/deb/build-in-container.sh
ls -l "$out"/nocs_"$VERSION"_*.deb
