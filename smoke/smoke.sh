#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
  echo "usage: $0 <archive.tar.gz>" >&2
  exit 2
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"; [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null || true' EXIT

tar -C "$WORK" -xzf "$ARCHIVE"
DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d)

NOCS_DATA_DIR=$(mktemp -d) "$DIR/bin/nocs" > "$WORK/out.log" 2>&1 &
PID=$!

for i in $(seq 1 30); do
  if curl -fsS http://localhost:8080/ >/dev/null 2>&1; then
    echo "NOCS is up after ${i}s"
    exit 0
  fi
  sleep 1
done

echo "NOCS did not start; logs:" >&2
cat "$WORK/out.log" >&2
exit 1
