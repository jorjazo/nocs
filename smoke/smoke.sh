#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 [--launcher <relative-path>] <archive>" >&2
  echo "  archive: .tar.gz or .zip produced by ./gradlew runtimeDist" >&2
  exit 2
}

LAUNCHER="bin/nocs"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --launcher)
      [ "$#" -ge 2 ] || usage
      LAUNCHER="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      ARCHIVE="${ARCHIVE:-$1}"
      shift
      ;;
  esac
done

[ -n "${ARCHIVE:-}" ] || usage
[ -f "$ARCHIVE" ] || { echo "archive not found: $ARCHIVE" >&2; exit 2; }

WORK=$(mktemp -d)
PID=""
trap 'if [ -n "${PID:-}" ]; then kill "$PID" 2>/dev/null || true; fi; rm -rf "$WORK"' EXIT

case "$ARCHIVE" in
  *.tar.gz|*.tgz)
    tar -C "$WORK" -xzf "$ARCHIVE"
    ;;
  *.zip)
    unzip -q -d "$WORK" "$ARCHIVE"
    ;;
  *)
    echo "unsupported archive type: $ARCHIVE" >&2
    exit 2
    ;;
esac

DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d)
[ -d "$DIR" ] || { echo "no top-level directory inside archive" >&2; exit 2; }

LAUNCHER_PATH="$DIR/$LAUNCHER"
[ -f "$LAUNCHER_PATH" ] || { echo "launcher missing: $LAUNCHER_PATH" >&2; exit 2; }
[ -x "$LAUNCHER_PATH" ] || chmod +x "$LAUNCHER_PATH" 2>/dev/null || true
# jlink image also needs java + helpers executable if the archive omitted modes
if [ -f "$DIR/bin/java" ]; then
  [ -x "$DIR/bin/java" ] || chmod +x "$DIR/bin/java" 2>/dev/null || true
fi
if [ -f "$DIR/lib/jspawnhelper" ]; then
  chmod +x "$DIR/lib/jspawnhelper" 2>/dev/null || true
fi
if [ -f "$DIR/lib/jexec" ]; then
  chmod +x "$DIR/lib/jexec" 2>/dev/null || true
fi

NOCS_DATA_DIR=$(mktemp -d) "$LAUNCHER_PATH" > "$WORK/out.log" 2>&1 &
PID=$!

for i in $(seq 1 60); do
  if curl -fsS http://localhost:8080/ >/dev/null 2>&1; then
    echo "NOCS is up after ${i}s (archive=$ARCHIVE launcher=$LAUNCHER)"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "launcher exited before serving HTTP; logs:" >&2
    cat "$WORK/out.log" >&2
    exit 1
  fi
  sleep 1
done

echo "NOCS did not start within 60s; logs:" >&2
cat "$WORK/out.log" >&2
exit 1
