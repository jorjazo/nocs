#!/usr/bin/env bash
# Build the Pi 5 image from main's head and publish it to the repository's testing
# images (the Image workflow run by hand with "testing"), wait for it, then print
# the image's address and Raspberry Pi Imager's list.
#
#   packaging/repo/testing-image.sh
set -euo pipefail

repo=jorjazo/nocs
apt=$(gh variable get NOCS_APT_URL --repo "$repo" 2>/dev/null || echo https://apt.nocs.app)
apt=${apt%/}

started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
out=$(gh workflow run image.yml --repo "$repo" --ref main -f testing=true 2>&1) \
    || { echo "$out" >&2; exit 1; }
run=$(grep -o 'runs/[0-9]*' <<<"$out" | cut -d/ -f2 || true)
for _ in 1 2 3 4 5 6; do  # an older gh does not print the run
    [[ -n $run ]] && break
    sleep 5
    run=$(gh run list --repo "$repo" --workflow image.yml --branch main --event workflow_dispatch \
        --created ">=$started" --limit 1 --json databaseId --jq '.[0].databaseId // empty')
done
[[ -n $run ]] || { echo "the run did not show up" >&2; exit 1; }
echo "Run: https://github.com/$repo/actions/runs/$run (about 13 minutes)"

if ! gh run watch "$run" --repo "$repo" --exit-status --interval 30; then
    echo "The run failed:" >&2
    gh run view "$run" --repo "$repo" --log-failed | tail -40 >&2
    exit 1
fi

list=$apt/images/rpi-imager.json
image=$(curl -fsSL "$list?run=$run" | python3 -c '
import json, sys
urls = [e["url"] for e in json.load(sys.stdin)["os_list"] if "/images/testing/" in e["url"]]
print(urls[0] if urls else "")
')
[[ -n $image ]] || { echo "Imager's list has no testing image: $list" >&2; exit 1; }

echo
echo "Image:   $image"
echo "SHA-256: $image.sha256"
echo "Imager:  $list"
echo "         rpi-imager --repo $list"
