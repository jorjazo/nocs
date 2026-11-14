#!/usr/bin/env bash
# Build the nocs .deb for this machine's architecture, and nocs-appliance (ADR 0025).
#
#   packaging/deb/build.sh            builds the web app, then the packages, into packaging/out
#
# Environment (defaults in brackets):
#   OUT [packaging/out]  VERSION [from server/pyproject.toml and git]
#   WEB_DIST [build web/ with pnpm]  PLATFORM [this machine's, e.g. linux/arm64]
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
out=${OUT:-$repo/packaging/out}
mkdir -p "$out"

# The pyproject version (0.1.0, 0.1.0rc1) is the tag's after its v; its package is
# 0.1.0 or 0.1.0~rc1, which sorts before 0.1.0. A tagged release is just that.
# Other builds add git<commits>.g<commit> (ADR 0045): after "~" while the version is
# not tagged yet (0.1.0~rc6~git231.g…, before 0.1.0~rc6), after "." once its tag is
# behind them (0.1.0~rc5.git219.g…, after 0.1.0~rc5), so that testing always moves on.
if [[ -z ${VERSION:-} ]]; then
    pep440=$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/server/pyproject.toml" | head -1)
    [[ $pep440 =~ ^([0-9]+\.[0-9]+\.[0-9]+)(rc([0-9]+))?$ ]] \
        || { echo "error: version $pep440 is neither X.Y.Z nor X.Y.ZrcN" >&2; exit 1; }
    base=${BASH_REMATCH[1]}${BASH_REMATCH[3]:+~rc${BASH_REMATCH[3]}}
    build="git$(git -C "$repo" rev-list --count HEAD).g$(git -C "$repo" rev-parse --short=7 HEAD)"
    if git -C "$repo" describe --exact-match --tags --match "v$pep440" >/dev/null 2>&1; then
        VERSION=$base
    elif git -C "$repo" merge-base --is-ancestor "refs/tags/v$pep440" HEAD 2>/dev/null; then
        VERSION="$base.$build"
    else
        VERSION="$base~$build"
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
"$repo/packaging/appliance/build.sh" "$VERSION" "$out"
ls -l "$out"/nocs_"$VERSION"_*.deb "$out"/nocs-appliance_"$VERSION"_all.deb
