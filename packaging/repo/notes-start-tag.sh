#!/usr/bin/env bash
# Print the tag a GitHub release's generated notes start from: the last release
# (not a release candidate) before <tag>, from the remote's tags. So v0.2.0 lists
# everything since v0.1.0, not only what changed since v0.2.0rc1, and v0.2.0rc2
# everything since v0.1.0 too. Prints nothing before the first release: the notes
# then start from the beginning.
#
#   packaging/repo/notes-start-tag.sh v0.2.0   (the Packages and Image workflows)
#
# Environment: REMOTE [origin]
set -euo pipefail

tag=${1:?usage: $0 <tag>}
release=${tag%%rc*}
git ls-remote --tags --refs "${REMOTE:-origin}" 'v*' | sed 's|.*refs/tags/||' \
    | awk -v r="$release" '/^v[0-9]+\.[0-9]+\.[0-9]+$/ && $0 != r' \
    | { cat; echo "$release"; } | sort -V \
    | awk -v r="$release" '$0 == r { if (prev != "") print prev; exit } { prev = $0 }'
