#!/usr/bin/env bash
# Tag a release on the remote's main and push the tag; the Packages and Image
# workflows then build it, publish it to the apt repository and make the GitHub
# release (ADR 0035). Do not create the release on GitHub by hand.
#
#   packaging/release.sh 0.1.0-rc.1       a release candidate (minor and major only)
#   packaging/release.sh 0.1.1            a release
#   packaging/release.sh --dry-run 0.2.0  check everything, tag nothing
#
# Versions: X.Y.Z or X.Y.0-rc.N (the tag is v<version>). server/pyproject.toml on
# main must already say the same version in PEP 440 (0.1.0rc1), as must
# nocs.__version__ and web/package.json: bump them in a pull request first.
#
# Environment: REMOTE [origin]
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

dry_run=0
if [[ ${1:-} == --dry-run ]]; then dry_run=1; shift; fi
[[ $# == 1 ]] || die "usage: $0 [--dry-run] <X.Y.Z | X.Y.0-rc.N>"
version=${1#v}
remote=${REMOTE:-origin}
cd "$(dirname "$0")/.."  # git and gh act on this repository

# The convention: SemVer in the tag, PEP 440 in Python, Debian in the package.
n='(0|[1-9][0-9]*)'
[[ $version =~ ^$n\.$n\.$n(-rc\.([1-9][0-9]*))?$ ]] \
    || die "$version is neither X.Y.Z nor X.Y.Z-rc.N (no leading zeros, N from 1)"
patch=${BASH_REMATCH[3]} rc=${BASH_REMATCH[5]}
release=${version%%-*}
[[ -z $rc || $patch == 0 ]] \
    || die "release candidates are for minor and major releases (X.Y.0-rc.N), not $version"
tag=v$version
pep440=$release${rc:+rc$rc}
deb=$release${rc:+~rc$rc}

# The version as main says it.
git fetch --quiet --tags "$remote" main
commit=$(git rev-parse "$remote/main")
show() { git show "$commit:$1"; }
said=$(show server/pyproject.toml | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)
[[ $said == "$pep440" ]] \
    || die "server/pyproject.toml on $remote/main says $said, not $pep440: bump it in a pull request"
show server/src/nocs/__init__.py | grep -qx "__version__ = \"$pep440\"" \
    || die "nocs.__version__ on $remote/main is not $pep440"
show web/package.json | grep -q "^  \"version\": \"$version\",$" \
    || die "web/package.json on $remote/main does not say $version"

# A new tag, newer than every release so far.
[[ -z $(git tag --list "$tag") ]] || die "tag $tag exists locally"
[[ -z $(git ls-remote --tags "$remote" "refs/tags/$tag") ]] || die "tag $tag exists on $remote"
! gh release view "$tag" >/dev/null 2>&1 || die "a GitHub release $tag exists"
while read -r other; do
    [[ ${other#v} =~ ^$n\.$n\.$n(-rc\.([1-9][0-9]*))?$ ]] || continue
    o=${other#v}
    o=${o%%-*}${BASH_REMATCH[5]:+~rc${BASH_REMATCH[5]}}
    dpkg --compare-versions "$deb" gt "$o" || die "$version is not newer than $other"
done < <(git tag --list 'v*')

# CI passed on that commit.
ci=$(gh run list --workflow ci.yml --commit "$commit" --limit 1 --json status,conclusion \
    --jq '.[0] | "\(.status) \(.conclusion)"')
[[ $ci == "completed success" ]] || die "CI on $remote/main ($commit) is '${ci:-not run}', not a success"

echo "release $version: tag $tag on $remote/main $(git log -1 --format='%h %s' "$commit")"
echo "packages $deb, image nocs-${deb//\~/-}-pi5-arm64.img.xz"
if [[ $dry_run == 1 ]]; then echo "dry run: nothing tagged"; exit 0; fi
read -r -p "Tag and push $tag? [y/N] " answer
[[ $answer == [yY] ]] || die "nothing tagged"

git tag -a -m "NOCS $version" "$tag" "$commit"
git push --quiet "$remote" "refs/tags/$tag"
echo "pushed $tag; the workflows build and publish it (about 15 minutes):"
echo "  gh run list --branch $tag"
